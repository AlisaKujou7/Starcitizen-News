"""New Comm-Link articles from the Star Citizen Wiki API."""
import html
import re
import time
from datetime import datetime, timedelta, timezone

from bot.feeds import FeedError, Item, request_with_retry

RSI_BASE = "https://robertsspaceindustries.com"
RSI_QUERY = {"channel": "", "series": "", "type": "", "text": "", "sort": "publish_new", "page": 1}
RSI_BLOCK = re.compile(r'(?=<a class="content-block)')
RSI_LINK = re.compile(r'href="(/comm-link/([a-z-]+)/(\d+)-[^"]*)"')
RSI_TITLE = re.compile(r'class="title(?: [^"]*)?">([^<]+)<')  # not "title-holder", which wraps it
RSI_AGE = re.compile(r'class="value">\s*(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago')
RSI_IMAGE = re.compile(r"url\('(https://[^']+)'\)")
RSI_BODY = re.compile(r'class="body">([\s\S]*?)</div>')
HTML_TAG = re.compile(r"<[^>]+>")
AGE_UNITS = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}

PAGE_SIZE = 30
# By date, not id: event pages can be published long after their id was created.
QUERY = {"page[size]": PAGE_SIZE, "sort": "-created_at", "include": "links"}
YOUTUBE = re.compile(r"https://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{6,})(?:[?&][\w=&%-]*)?")
THUMBNAILS = "https://img.youtube.com/vi"
COVER_BUDGET = 60
MAX_SUMMARY = 300
MARKUP = re.compile(r"h[1-6]", re.IGNORECASE)
SITE_NAME = re.compile(r"\s*\|\s*Star Citizen\s*$|^\s*Star Citizen\s*\|\s*", re.IGNORECASE)
GREETING = re.compile(r"^[^.!?]*?\b(?:hello|hi|greetings)[ ,]+(?:everyone|citizens|all)\b[,!.:]*\s*", re.IGNORECASE)
SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
WEB_MENU = ("Discover the ship", "Community Highlights", "View more on Community Hub")
UNDEFINED = "Undefined"
META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
OG_IMAGE = re.compile(r"""property\s*=\s*["']og:image["']""", re.IGNORECASE)
CONTENT = re.compile(r"""content\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def summarize(text, title):
    """The opening of an article, without file names, markup, site menus, the repeated title or a greeting.

    No summary is better than a messy one, so text with no complete sentence gives an empty result.
    """
    if not isinstance(text, str):
        return ""
    lines = []
    for line in text.splitlines():
        words = [w for w in line.split() if "_" not in w and not MARKUP.fullmatch(w)]
        cleaned = " ".join(words)
        if cleaned and not any(phrase in cleaned for phrase in WEB_MENU):
            lines.append(cleaned)
    if not lines:
        return ""
    base = SITE_NAME.sub("", title)
    for prefix in (base, base.split(" - ")[0]):  # a title may carry a date the article's first line does not
        if prefix and lines[0].lower().startswith(prefix.lower()):
            lines[0] = lines[0][len(prefix):].strip()
            break
    lines[0] = GREETING.sub("", lines[0]).strip()
    summary = "\n".join(line for line in lines if line)
    if len(summary) > MAX_SUMMARY:
        summary = _shorten(summary)
    if not SENTENCE_END.search(summary):
        return ""
    return summary


def _shorten(summary):
    """End on a complete sentence when one fits, otherwise on a whole word."""
    cut = summary[:MAX_SUMMARY]
    ends = list(SENTENCE_END.finditer(cut))
    if ends:
        return cut[:ends[-1].end()]
    return summary[:MAX_SUMMARY - 1].rsplit(None, 1)[0] + "…"


def parse_rsi(body, now):
    """RSI's own news list. It sees new articles first, but has no links and only a rough age."""
    html_list = body.get("data") if isinstance(body, dict) and body.get("success") == 1 else None
    if not isinstance(html_list, str):
        raise FeedError("sc_commlink: รายการข่าวของ RSI ใช้ไม่ได้")
    blocks = [b for b in RSI_BLOCK.split(html_list) if b.startswith("<a class")]
    if not blocks:
        raise FeedError("sc_commlink: รายการข่าวของ RSI ไม่มีข่าว")
    items = []
    for block in blocks:
        link, title = RSI_LINK.search(block), RSI_TITLE.search(block)
        if not (link and title):
            raise FeedError("sc_commlink: รูปแบบรายการข่าวของ RSI เปลี่ยน")
        age, image, text = RSI_AGE.search(block), RSI_IMAGE.search(block), RSI_BODY.search(block)
        summary = " ".join(html.unescape(HTML_TAG.sub(" ", text.group(1))).split()) if text else ""
        items.append(
            Item(
                id=link.group(3),
                feed="sc_commlink",
                kind="commlink",
                title=html.unescape(title.group(1)).strip(),
                url=RSI_BASE + link.group(1),
                description=_shorten(summary) if len(summary) > MAX_SUMMARY else summary,
                timestamp=now - int(age.group(1)) * AGE_UNITS[age.group(2)] if age else None,
                image=image.group(1) if image else None,
                category=link.group(2).capitalize(),
            )
        )
    return items


def merge(wiki_items, rsi_items):
    """One item per article: the Wiki's video link and date, with RSI's cleaner summary when it has one."""
    wiki_by_id = {item.id: item for item in wiki_items}
    merged = []
    for rsi_item in rsi_items:
        wiki_item = wiki_by_id.pop(rsi_item.id, None)
        if wiki_item is None:
            merged.append(rsi_item)
            continue
        wiki_item.description = rsi_item.description or wiki_item.description
        merged.append(wiki_item)
    return merged + list(wiki_by_id.values())


def find_video(links):
    """The article's YouTube link. With several we cannot tell which is the main one, so we use none."""
    if not isinstance(links, list):
        return None
    hrefs = {link.get("href") for link in links if isinstance(link, dict)}
    videos = [href for href in hrefs if isinstance(href, str) and YOUTUBE.fullmatch(href)]
    return videos[0] if len(videos) == 1 else None


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
        summary = summarize(text, title)
        channel = row.get("channel")
        category = channel if channel and channel != UNDEFINED else None
        items.append(
            Item(
                id=str(item_id),
                feed="sc_commlink",
                kind="commlink",
                title=title,
                url=url,
                description=summary,
                timestamp=moment,
                image=None,
                category=category,
                compact=not category and not summary and not row.get("images_count"),
                video=find_video(row.get("links")),
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


def video_thumbnail(video):
    """A video's cover. Not every video has the largest size, and the smaller one always exists."""
    video_id = YOUTUBE.fullmatch(video).group(1)
    best = f"{THUMBNAILS}/{video_id}/maxresdefault.jpg"
    try:
        request_with_retry("GET", best)
    except FeedError:
        return f"{THUMBNAILS}/{video_id}/hqdefault.jpg"
    return best


def add_covers(items, budget=COVER_BUDGET, clock=time.monotonic):
    """Open article pages only for items about to be sent. Past the budget, the rest go without a picture."""
    start = clock()
    for item in items:
        if clock() - start >= budget:
            break
        item.image = (video_thumbnail(item.video) if item.video else cover_image(item.url)) or item.image


def _fetch_wiki(url, tz):
    response = request_with_retry("GET", url, params=QUERY, headers={"Accept": "application/json"})
    try:
        body = response.json()
    except ValueError:
        raise FeedError("sc_commlink: คำตอบไม่ใช่ JSON") from None
    return parse(body, tz)


def _fetch_rsi(url, now):
    response = request_with_retry("POST", url, json=RSI_QUERY, headers={"Accept": "application/json"})
    try:
        body = response.json()
    except ValueError:
        raise FeedError("sc_commlink: คำตอบของ RSI ไม่ใช่ JSON") from None
    return parse_rsi(body, now)


def fetch(url, tz, rsi_url=None, now=None, warn=print):
    """Either source alone is enough. Only both failing counts as this feed failing."""
    if not rsi_url:
        return _fetch_wiki(url, tz)
    wiki_items, rsi_items, problems = [], [], []
    try:
        wiki_items = _fetch_wiki(url, tz)
    except FeedError as exc:
        problems.append(f"Star Citizen Wiki: {exc}")
    try:
        rsi_items = _fetch_rsi(rsi_url, now or datetime.now(timezone.utc))
    except FeedError as exc:
        problems.append(f"RSI: {exc}")
    if len(problems) == 2:
        raise FeedError("; ".join(problems))
    for problem in problems:
        warn(f"sc_commlink ใช้แหล่งเดียวรอบนี้ เพราะ {problem}")
    return merge(wiki_items, rsi_items)
