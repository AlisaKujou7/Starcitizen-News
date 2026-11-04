"""Build Discord embeds and send them to a webhook."""
import time

import requests

from bot import feeds

COLORS = {"commlink": 0x1E90FF, "status": 0xE53935}
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_EMBEDS = 10
MAX_TOTAL = 6000
MAX_429 = 5
MAX_WAIT = 60
MAX_URL = 512
BUTTON_LABELS = {"commlink": "อ่านเพิ่มเติม", "status": "ดูสถานะ"}
COMPACT_BUTTON_LABEL = "เพิ่มเติม"
HUB_BUTTONS = {
    "commlink": ("Comm-Link ทั้งหมด", "https://robertsspaceindustries.com/comm-link"),
    "status": ("หน้าสถานะ", "https://status.robertsspaceindustries.com/"),
}


class DiscordError(Exception):
    """A send failed. The message never contains the webhook URL."""


def build_embed(item):
    embed = {
        "title": item.title[:MAX_TITLE],
        "url": item.url,
        "color": COLORS[item.kind],
    }
    if item.compact:
        return embed
    if item.category:
        embed["footer"] = {"text": item.category}  # Discord shows footer text just before the timestamp
    if item.description:
        embed["description"] = item.description[:MAX_DESCRIPTION]
    if item.timestamp:
        embed["timestamp"] = item.timestamp.isoformat()
    if item.image:
        embed["image"] = {"url": item.image}
    return embed


def _batch_embed(items):
    lines = []
    used = 0
    for index, item in enumerate(items):
        line = f"- [{item.title[:100]}]({item.url})"
        # Leave room for the "and N more" line.
        if used + len(line) + 1 > MAX_DESCRIPTION - 40:
            lines.append(f"…และอีก {len(items) - index} รายการ")
            break
        lines.append(line)
        used += len(line) + 1
    color = COLORS["status"] if any(i.kind == "status" for i in items) else COLORS["commlink"]
    return {"title": f"ข่าวใหม่ {len(items)} รายการ", "description": "\n".join(lines), "color": color}


def _button_label(item):
    return COMPACT_BUTTON_LABEL if item.compact else BUTTON_LABELS[item.kind]


def _link_button(label, url):
    return {"type": 2, "style": 5, "label": label, "url": url}


def _payload(embed, mention, buttons):
    payload = {"embeds": [embed], "allowed_mentions": {"parse": ["roles"] if mention else []}}
    if mention:
        payload["content"] = mention
    # Discord rejects the whole message over one bad button, so an overlong URL only loses its button.
    usable = [b for b in buttons if len(b["url"]) <= MAX_URL]
    if usable:
        payload["components"] = [{"type": 1, "components": usable}]
    return payload


def build_messages(items, threshold, mention=""):
    """Returns (payload, items covered) pairs. Above the threshold everything becomes one message."""
    if len(items) > threshold:
        kinds = {item.kind for item in items}
        hubs = [_link_button(*hub) for kind, hub in HUB_BUTTONS.items() if kind in kinds]
        return [(_payload(_batch_embed(items), mention, hubs), list(items))]
    return [
        (_payload(build_embed(item), mention, [_link_button(_button_label(item), item.url)]), [item])
        for item in items
    ]


def _retry_after(response):
    try:
        value = response.json().get("retry_after")
    except (ValueError, AttributeError):
        value = None
    if value is None:
        value = response.headers.get("Retry-After", 1)
    try:
        return min(max(float(value), 0), MAX_WAIT)
    except (TypeError, ValueError):
        return 1


def send(url, payload):
    failures = 0
    limited = 0
    while True:
        try:
            # Without with_components, Discord silently drops buttons sent through a plain webhook.
            response = requests.request(
                "POST", url, params={"with_components": "true"}, json=payload, timeout=feeds.TIMEOUT
            )
        except requests.RequestException as exc:
            problem = type(exc).__name__
        else:
            status = response.status_code
            if status < 300:
                return
            if status == 429:
                limited += 1
                if limited >= MAX_429:
                    raise DiscordError("HTTP 429 ซ้ำหลายครั้ง") from None
                time.sleep(_retry_after(response))
                continue
            if status < 500:
                raise DiscordError(f"HTTP {status}") from None
            problem = f"HTTP {status}"
        failures += 1
        if failures > feeds.RETRIES:
            raise DiscordError(problem) from None
        feeds.backoff(failures)
