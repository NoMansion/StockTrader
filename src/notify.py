"""Short alert messages to the private Discord report channel (the same bot and channel as the daily report).

Settings come from .env: DISCORD_REPORT_CHANNEL_ID, and DISCORD_TOKEN or else the bot's own .env at
DISCORD_BOT_ENV (default: DiscordBot/.env in the folder that holds this project). post_text() never raises: an alert that cannot be sent is
reported back as False so the caller can log it, and must never break the job it reports on.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

UA = "DiscordBot (https://example.invalid, 1.0)"


def discord_token() -> str | None:
    if os.environ.get("DISCORD_TOKEN"):
        return os.environ["DISCORD_TOKEN"]
    p = Path(os.environ.get("DISCORD_BOT_ENV", Path(__file__).resolve().parents[2] / "DiscordBot" / ".env"))
    if p.exists():
        from dotenv import dotenv_values
        return dotenv_values(p).get("DISCORD_TOKEN")
    return None


def post_text(text: str, channel: str | None = None, token: str | None = None) -> tuple[bool, str]:
    """Post one message. Returns (ok, detail)."""
    channel = channel or os.environ.get("DISCORD_REPORT_CHANNEL_ID")
    token = token or discord_token()
    if not (channel and token):
        return False, "DISCORD_REPORT_CHANNEL_ID or the Discord token is not set"
    try:
        import requests
        url = f"https://discord.com/api/v10/channels/{channel}/messages"
        h = {"Authorization": f"Bot {token}", "User-Agent": UA, "Content-Type": "application/json"}
        body = json.dumps({"content": text[:1990], "allowed_mentions": {"parse": []}})
        for _ in range(3):
            r = requests.post(url, headers=h, data=body, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
                continue
            if r.status_code >= 400:
                return False, f"Discord answered {r.status_code}: {r.text[:200]}"
            return True, "posted"
        return False, "Discord kept rate-limiting"
    except Exception as ex:   # noqa: BLE001
        return False, f"{type(ex).__name__}: {str(ex)[:200]}"
