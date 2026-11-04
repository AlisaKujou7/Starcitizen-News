"""Read and write state.json: which items were already announced, per feed."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

KEEPALIVE_DAYS = 50
MAX_AGE_DAYS = 14


class StateError(Exception):
    """state.json exists but cannot be trusted. Never reset it: that would re-announce or lose history."""


def load(path):
    path = Path(path)
    if not path.exists():
        return {"version": 1, "feeds": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StateError(f"อ่าน {path.name} ไม่ได้: {type(exc).__name__}") from None
    feeds = data.get("feeds") if isinstance(data, dict) else None
    if not isinstance(feeds, dict) or not all(isinstance(f, dict) and isinstance(f.get("seen"), list) for f in feeds.values()):
        raise StateError(f"รูปแบบของ {path.name} ไม่ถูกต้อง")
    return data


def save(path, data):
    """Atomic and deterministic, so an unchanged state leaves the file byte-identical."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _feed(data, name):
    return data["feeds"].setdefault(name, {"seen": [], "failing_since": None})


def is_bootstrapped(data, name):
    return bool(data["feeds"].get(name, {}).get("seen"))


def bootstrap(data, name, items):
    feed = _feed(data, name)
    feed["seen"] = [item.id for item in items]


def new_items(data, name, items, now=None, max_age_days=MAX_AGE_DAYS):
    now = now or datetime.now(timezone.utc)
    seen = set(_feed(data, name)["seen"])
    found = []
    for item in items:
        if item.id in seen:
            continue
        if item.timestamp and now - item.timestamp > timedelta(days=max_age_days):
            continue  # an old article reappearing on the first page is not news
        found.append(item)
    return found


def mark_sent(data, item):
    seen = _feed(data, item.feed)["seen"]
    if item.id not in seen:
        seen.append(item.id)


def record_failure(data, name, now_iso):
    feed = _feed(data, name)
    if not feed.get("failing_since"):
        feed["failing_since"] = now_iso


def record_success(data, name):
    _feed(data, name)["failing_since"] = None


def keepalive_due(last_commit_epoch, now_epoch, days=KEEPALIVE_DAYS):
    return now_epoch - last_commit_epoch >= days * 86400
