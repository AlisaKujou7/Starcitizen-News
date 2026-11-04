"""New Comm-Link articles from the Star Citizen Wiki API."""
import html
import re
import time
from datetime import datetime

from bot.feeds import FeedError, Item, format_local, request_with_retry

PAGE_SIZE = 30
COVER_BUDGET = 60
META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
OG_IMAGE = re.compile(r"""property\s*=\s*["']og:image["']""", re.IGNORECASE)
CONTENT = re.compile(r"""content\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def parse(body, tz):
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        raise FeedError("sc_commlink: ไม่มีรายการใน data")
    items = []
    for row in rows:
        try:
            item_id, title, url = row["id"], row["title"], row["rsi_url"]
            created = row.get("created_at")
            moment = datetime.fromisoformat(created) if created else None
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise FeedError(f"sc_commlink: รูปแบบข้อมูลเปลี่ยน ({type(exc).__name__})") from None
        channel = row.get("channel") or "ไม่ระบุ"
        items.append(
            Item(
                id=str(item_id),
                feed="sc_commlink",
                kind="commlink",
                title=title,
                url=url,
                description=f"หมวด: {channel}\nวันที่: {format_local(moment, tz)}",
                timestamp=moment,
                image=None,
            )
        )
    return items


def cover_image(url):
    """The article's cover (its og:image). A missing cover must never stop a message, so this returns None."""
    try:
        page = request_with_retry("GET", url).text
    except FeedError:
        return None
    for tag in META_TAG.findall(page):
        if OG_IMAGE.search(tag):
            found = CONTENT.search(tag)
            cover = html.unescape((found.group(1) or found.group(2) or "") if found else "")
            if not cover.startswith("https://"):
                return None
            return cover
    return None


def add_covers(items, budget=COVER_BUDGET, clock=time.monotonic):
    """Open article pages only for items about to be sent. Past the budget, the rest go without a picture."""
    start = clock()
    for item in items:
        if clock() - start >= budget:
            break
        item.image = cover_image(item.url)


def fetch(url, tz):
    response = request_with_retry(
        "GET", url, params={"page[size]": PAGE_SIZE, "include": "images"}, headers={"Accept": "application/json"}
    )
    try:
        body = response.json()
    except ValueError:
        raise FeedError("sc_commlink: คำตอบไม่ใช่ JSON") from None
    return parse(body, tz)
