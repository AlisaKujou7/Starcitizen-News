"""Shared feed types and the HTTP helper used for every request the bot makes."""
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests

TIMEOUT = 15
RETRIES = 2
WEBHOOK_RE = re.compile(r"https?://\S*/webhooks/\S+", re.IGNORECASE)


class FeedError(Exception):
    """A source could not be read or did not look the way we expect."""


@dataclass
class Item:
    id: str
    feed: str
    kind: str
    title: str
    url: str
    description: str
    timestamp: Optional[datetime]
    image: Optional[str]
    category: Optional[str] = None
    compact: bool = False  # nothing but a title and a link, such as a game code giveaway
    video: Optional[str] = None


def redact(text):
    """Remove webhook URLs from anything that may reach a log."""
    text = str(text)
    secret = os.environ.get("SC_WEBHOOK")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return WEBHOOK_RE.sub("[REDACTED]", text)


def backoff(attempt):
    time.sleep(float(os.environ.get("BOT_RETRY_BACKOFF", "1")) * attempt)


def request_with_retry(method, url, **kwargs):
    """Timeout on every request; connection errors and 5xx/429 get RETRIES more tries."""
    problem = "unknown"
    for attempt in range(RETRIES + 1):
        if attempt:
            backoff(attempt)
        try:
            response = requests.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            problem = type(exc).__name__
            continue
        if response.status_code < 400:
            return response
        problem = f"HTTP {response.status_code}"
        if response.status_code != 429 and response.status_code < 500:
            break
    raise FeedError(redact(f"{url}: {problem}")) from None


def format_local(moment, tz):
    if moment is None:
        return "ไม่ระบุ"
    return moment.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M น.")
