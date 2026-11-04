"""New Comm-Link articles from the Star Citizen Wiki API."""
import html
import re
import time
from datetime import datetime

from bot.feeds import FeedError, Item, request_with_retry

PAGE_SIZE = 30
COVER_BUDGET = 60
MAX_SUMMARY = 300
MARKUP = re.compile(r"h[1-6]", re.IGNORECASE)
SITE_NAME = re.compile(r"\s*\|\s*Star Citizen\s*$|^\s*Star Citizen\s*\|\s*", re.IGNORECASE)
META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
OG_IMAGE = re.compile(r"""property\s*=\s*["']og:image["']""", re.IGNORECASE)
CONTENT = re.compile(r"""content\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def summarize(text, title):
    """The opening of an article, without leftover file names, markup or the repeated title."""
    if not isinstance(text, str):
        return ""
    lines = []
    for line in text.splitlines():
        words = [w for w in line.split() if "_" not in w and not MARKUP.fullmatch(w)]
        if words:
            lines.append(" ".join(words))
    base = SITE_NAME.sub("", title)
    if lines and lines[0].lower().startswith(base.lower()):
        lines[0] = lines[0][len(base):].strip()
        if not lines[0]:
            lines.pop(0)
    summary = "\n".join(lines)
    if len(summary) > MAX_SUMMARY:
        summary = summary[:MAX_SUMMARY - 1].rsplit(None, 1)[0] + "…"
    return summary


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
            text = (row.get("translations") or {}).get("en_EN")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise FeedError(f"sc_commlink: รูปแบบข้อมูลเปลี่ยน ({type(exc).__name__})") from None
        items.append(
            Item(
                id=str(item_id),
                feed="sc_commlink",
                kind="commlink",
                title=title,
                url=url,
                description=summarize(text, title),
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
        "GET", url, params={"page[size]": PAGE_SIZE}, headers={"Accept": "application/json"}
    )
    try:
        body = response.json()
    except ValueError:
        raise FeedError("sc_commlink: คำตอบไม่ใช่ JSON") from None
    return parse(body, tz)
