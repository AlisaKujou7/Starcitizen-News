"""New Comm-Link articles from the Star Citizen Wiki API."""
from datetime import datetime

from bot.feeds import FeedError, Item, format_local, request_with_retry

PAGE_SIZE = 30


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
        images = row.get("images") or []
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
                image=next((i["rsi_url"] for i in images if isinstance(i, dict) and i.get("rsi_url")), None),
            )
        )
    return items


def fetch(url, tz):
    response = request_with_retry(
        "GET", url, params={"page[size]": PAGE_SIZE, "include": "images"}, headers={"Accept": "application/json"}
    )
    try:
        body = response.json()
    except ValueError:
        raise FeedError("sc_commlink: คำตอบไม่ใช่ JSON") from None
    return parse(body, tz)
