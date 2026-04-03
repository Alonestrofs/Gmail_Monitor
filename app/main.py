from __future__ import annotations

import logging
import secrets
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from googleapiclient.errors import HttpError

from app.config import get_missing_settings, load_settings
from app.db import Database
from app.gmail_client import (
    build_gmail_service,
    create_oauth_flow,
    credentials_from_tokens,
    ensure_fresh_tokens,
    extract_latest_history_id,
    fetch_new_messages,
    fetch_profile,
    is_history_too_old,
    serialize_credentials,
)
from app.webhooks import send_webhook


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    settings = load_settings()
    settings_error = None
except RuntimeError as error:
    settings = None
    settings_error = str(error)

db = Database("mailboxes.db")

app_state: dict[str, Any] = {
    "oauth_states": {},
    "stop_event": threading.Event(),
    "poll_thread": None,
}


def _poll_loop() -> None:
    logger.info("Background polling started")
    stop_event: threading.Event = app_state["stop_event"]
    while not stop_event.wait(_poll_interval_seconds()):
        _poll_all_mailboxes()
    logger.info("Background polling stopped")


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event: threading.Event = app_state["stop_event"]
    stop_event.clear()
    poll_thread = threading.Thread(target=_poll_loop, daemon=True)
    app_state["poll_thread"] = poll_thread
    poll_thread.start()
    try:
        yield
    finally:
        stop_event.set()
        if poll_thread.is_alive():
            poll_thread.join(timeout=5)


app = FastAPI(title="Gmail Webhook Bridge", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    if settings_error:
        return {
            "status": "misconfigured",
            "missing": get_missing_settings(),
            "detail": settings_error,
        }
    return {"status": "ok"}


@app.get("/auth/start")
def auth_start() -> RedirectResponse:
    active_settings = _require_settings()
    state = secrets.token_urlsafe(32)
    flow = create_oauth_flow(active_settings, state=state)
    authorization_url, returned_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    app_state["oauth_states"][returned_state] = {"created_at": time.time()}
    return RedirectResponse(authorization_url)


@app.get("/auth/callback")
def auth_callback(request: Request) -> JSONResponse:
    active_settings = _require_settings()
    state = request.query_params.get("state")
    if not state or state not in app_state["oauth_states"]:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    flow = create_oauth_flow(active_settings, state=state)
    flow.fetch_token(authorization_response=str(request.url))
    creds = flow.credentials

    service = build_gmail_service(creds)
    profile = fetch_profile(service)
    email = profile["emailAddress"]
    history_id = extract_latest_history_id(service)

    mailbox_id = db.upsert_mailbox(
        email=email,
        tokens=serialize_credentials(creds),
        last_history_id=history_id,
    )
    app_state["oauth_states"].pop(state, None)

    return JSONResponse(
        {
            "status": "connected",
            "mailbox": {
                "id": mailbox_id,
                "email": email,
                "last_history_id": history_id,
            },
        }
    )


@app.get("/mailboxes")
def list_mailboxes() -> dict[str, list[dict[str, Any]]]:
    rows = db.list_mailboxes()
    return {
        "mailboxes": [
            {
                "id": row["id"],
                "email": row["email"],
                "last_history_id": row["last_history_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    }


@app.delete("/mailboxes/{mailbox_id}")
def delete_mailbox(mailbox_id: int) -> dict[str, Any]:
    deleted = db.delete_mailbox(mailbox_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    return {"status": "deleted", "mailbox_id": mailbox_id}


@app.post("/poll-now")
def poll_now() -> dict[str, str]:
    _poll_all_mailboxes()
    return {"status": "poll_finished"}


def _poll_all_mailboxes() -> None:
    if settings_error:
        logger.warning("Skipping polling because configuration is incomplete: %s", settings_error)
        return
    for mailbox in db.list_mailboxes():
        try:
            _poll_mailbox(mailbox)
        except Exception:
            logger.exception("Polling failed for mailbox %s", mailbox["email"])


def _poll_mailbox(mailbox: dict[str, Any]) -> None:
    active_settings = _require_settings()
    creds = credentials_from_tokens(mailbox["tokens"])
    creds = ensure_fresh_tokens(creds)
    db.update_tokens(mailbox["id"], serialize_credentials(creds))

    service = build_gmail_service(creds)
    start_history_id = mailbox.get("last_history_id")
    if not start_history_id:
        db.update_history_id(mailbox["id"], extract_latest_history_id(service))
        return

    try:
        messages, latest_history_id = fetch_new_messages(service, start_history_id)
    except HttpError as error:
        if not is_history_too_old(error):
            raise
        logger.warning("History cursor expired for %s, rebuilding baseline", mailbox["email"])
        db.update_history_id(mailbox["id"], extract_latest_history_id(service))
        return

    for message in messages:
        payload = {
            "event": "gmail.new_message",
            "mailbox": {
                "id": mailbox["id"],
                "email": mailbox["email"],
            },
            "message": message,
        }
        send_webhook(active_settings.webhook_url, payload)

    if latest_history_id and latest_history_id != start_history_id:
        db.update_history_id(mailbox["id"], latest_history_id)


def _require_settings():
    if settings is None:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Application is not configured",
                "missing": get_missing_settings(),
            },
        )
    return settings


def _poll_interval_seconds() -> int:
    return settings.poll_interval_seconds if settings else 45
