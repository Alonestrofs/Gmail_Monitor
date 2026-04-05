# Gmail Webhook Bridge

Small FastAPI service that connects multiple Gmail mailboxes and emits a webhook event whenever a new message arrives.

## What it does

- Supports 2 or more Gmail accounts at the same time.
- Uses Gmail OAuth per mailbox.
- Stores mailbox tokens and sync state in SQLite.
- Polls Gmail history in the background and posts new-mail events to one webhook URL.
- Exposes simple HTTP endpoints to connect, inspect, and remove mailboxes.

## Setup

1. Create a Google Cloud project.
2. Enable the Gmail API.
3. Create an OAuth client for a web application.
4. Set the redirect URI to `http://localhost:8000/auth/callback` or your deployed callback URL.
5. Add `.env` to `./app` and fill in the OAuth values plus your webhook URL.
6. Install dependencies:

```bash
pip install -r requirements.txt
```

7. Run the app:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
If you are using Powershell, you may need to use this command instead
```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
## Connect mailboxes

Open this URL in a browser:

```text
http://localhost:8000/auth/start
```

Repeat the same flow for each Gmail account you want to connect.

## API

- `GET /health`
- `GET /auth/start`
- `GET /auth/callback`
- `GET /mailboxes`
- `DELETE /mailboxes/{mailbox_id}`
- `POST /poll-now`

## Webhook payload

```json
{
  "event": "gmail.new_message",
  "mailbox": {
    "id": 1,
    "email": "person@gmail.com"
  },
  "message": {
    "id": "18c123...",
    "thread_id": "18c120...",
    "history_id": "123456",
    "subject": "Example subject",
    "from": "Sender <sender@example.com>",
    "snippet": "First lines of the email",
    "internal_date": "2026-04-03T15:34:12+00:00",
    "label_ids": ["INBOX", "UNREAD"]
  }
}
```

This payload is generic on purpose so you can forward it to Telegram, Discord, or another automation layer.

## Notes

- Gmail history can expire. If that happens, the app automatically resyncs the mailbox baseline and continues.
- The first sync establishes a baseline and does not emit notifications for old mail.
- For production, put this behind a real domain and HTTPS, then update `GMAIL_REDIRECT_URI`.
