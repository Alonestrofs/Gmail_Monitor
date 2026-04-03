from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import Settings, should_allow_insecure_oauth_transport


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def create_oauth_flow(settings: Settings, state: str | None = None) -> Flow:
    if should_allow_insecure_oauth_transport():
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.gmail_redirect_uri],
            }
        },
        scopes=SCOPES,
        state=state,
        redirect_uri=settings.gmail_redirect_uri,
    )


def credentials_from_tokens(tokens: dict[str, Any]) -> Credentials:
    return Credentials.from_authorized_user_info(tokens, SCOPES)


def ensure_fresh_tokens(creds: Credentials) -> Credentials:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def serialize_credentials(creds: Credentials) -> dict[str, Any]:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def build_gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def fetch_profile(service) -> dict[str, Any]:
    return service.users().getProfile(userId="me").execute()


def extract_latest_history_id(service) -> str | None:
    messages = (
        service.users()
        .messages()
        .list(userId="me", maxResults=1, labelIds=["INBOX"])
        .execute()
    )
    items = messages.get("messages", [])
    if not items:
        return None
    message = (
        service.users()
        .messages()
        .get(userId="me", id=items[0]["id"], format="metadata")
        .execute()
    )
    return message.get("historyId")


def fetch_new_messages(service, start_history_id: str) -> tuple[list[dict[str, Any]], str | None]:
    next_page_token: str | None = None
    latest_history_id: str | None = start_history_id
    message_ids: set[str] = set()

    while True:
        response = (
            service.users()
            .history()
            .list(
                userId="me",
                startHistoryId=start_history_id,
                historyTypes=["messageAdded"],
                pageToken=next_page_token,
            )
            .execute()
        )
        latest_history_id = response.get("historyId", latest_history_id)

        for history_entry in response.get("history", []):
            for added in history_entry.get("messagesAdded", []):
                message = added.get("message", {})
                labels = set(message.get("labelIds", []))
                if "INBOX" in labels:
                    message_ids.add(message["id"])

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    messages = [fetch_message(service, message_id) for message_id in sorted(message_ids)]
    return messages, latest_history_id


def fetch_message(service, message_id: str) -> dict[str, Any]:
    response = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Subject"],
        )
        .execute()
    )
    headers = {
        header["name"].lower(): header["value"]
        for header in response.get("payload", {}).get("headers", [])
    }
    return {
        "id": response["id"],
        "thread_id": response.get("threadId"),
        "history_id": response.get("historyId"),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "snippet": response.get("snippet", ""),
        "internal_date": _format_internal_date(response.get("internalDate")),
        "label_ids": response.get("labelIds", []),
    }


def _format_internal_date(value: str | None) -> str | None:
    if not value:
        return None
    dt = datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    return dt.isoformat()


def is_history_too_old(error: HttpError) -> bool:
    if error.resp.status != 404:
        return False
    return "startHistoryId" in str(error)
