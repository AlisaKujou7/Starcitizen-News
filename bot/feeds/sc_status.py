"""RSI status incidents from the public RSS feed."""
import re
from datetime import datetime, timezone

import feedparser

from bot.feeds import FeedError, Item, format_local, request_with_retry

PREFIX = re.compile(r"^\[([^\]]+)\]\s*(.+)$")


def parse(text, tz):
    # Always bytes: given a str, feedparser may treat it as a URL or a file path to open.
    entries = feedparser.parse(text.encode("utf-8")).entries
    if not entries:
        raise FeedError("sc_status: ไม่มีรายการใน feed")
    items = []
    for entry in entries:
        guid, raw_title, link = entry.get("id"), entry.get("title"), entry.get("link")
        if not (guid and raw_title and link):
            raise FeedError("sc_status: รูปแบบข้อมูลเปลี่ยน")
        match = PREFIX.match(raw_title)
        status, title = match.groups() if match else ("ไม่ระบุ", raw_title)
        parsed = entry.get("published_parsed")
        moment = datetime(*parsed[:6], tzinfo=timezone.utc) if parsed else None
        items.append(
            Item(
                id=guid,
                feed="sc_status",
                kind="status",
                title=title,
                url=link,
                description=f"สถานะ: {status}\nเวลาเริ่ม: {format_local(moment, tz)}",
                timestamp=moment,
                image=None,
            )
        )
    return items


def fetch(url, tz):
    response = request_with_retry("GET", url)
    return parse(response.content.decode("utf-8", errors="replace"), tz)
