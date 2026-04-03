from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests


logger = logging.getLogger(__name__)


def send_webhook(webhook_url: str, payload: dict) -> None:
    request_body = _build_request_body(webhook_url, payload)
    response = requests.post(webhook_url, json=request_body, timeout=15)
    if not response.ok:
        logger.error(
            "Webhook delivery failed with status %s: %s",
            response.status_code,
            response.text[:500],
        )
    response.raise_for_status()
    logger.info("Webhook sent with status %s", response.status_code)


def _build_request_body(webhook_url: str, payload: dict) -> dict:
    if _is_discord_webhook(webhook_url):
        return _build_discord_payload(payload)
    return payload


def _is_discord_webhook(webhook_url: str) -> bool:
    parsed = urlparse(webhook_url)
    return parsed.netloc in {"discord.com", "canary.discord.com", "ptb.discord.com"} and parsed.path.startswith("/api/webhooks/")


def _build_discord_payload(payload: dict) -> dict:
    mailbox = payload.get("mailbox", {})
    message = payload.get("message", {})
    subject = message.get("subject") or "(no subject)"
    sender = message.get("from") or "Unknown sender"
    snippet = (message.get("snippet") or "").strip() or "(no preview)"
    snippet = snippet[:1000]
    label_ids = message.get("label_ids") or []

    embed_fields = [
        {"name": "Mailbox", "value": str(mailbox.get("email", "unknown")), "inline": False},
        {"name": "From", "value": str(sender), "inline": False},
        {"name": "Labels", "value": ", ".join(label_ids) if label_ids else "None", "inline": False},
    ]

    internal_date = message.get("internal_date")
    if internal_date:
        embed_fields.append({"name": "Received", "value": str(internal_date), "inline": False})

    return {
        "content": "New Gmail message received",
        "embeds": [
            {
                "title": subject[:256],
                "description": snippet,
                "color": 3447003,
                "fields": embed_fields,
                "footer": {"text": f"Message ID: {message.get('id', 'unknown')}"},
            }
        ],
    }
