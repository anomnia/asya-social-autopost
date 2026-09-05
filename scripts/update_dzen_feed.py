"""
Шаг 5: генерируем HTML-страницу под каждый новый пост и пересобираем
docs/dzen.xml — RSS-фид, который Дзен сам периодически скачивает и
импортирует из него новые материалы (официального API для публикации в
Дзен не существует, поэтому используется именно такой способ).

state/pending.json на каждом запуске полностью перезаписывается только
новыми постами (см. fetch_telegram.py) и не хранит историю, поэтому
накопленный список уже опубликованных в Дзен статей хранится отдельно —
в state/dzen_articles.json. В самом RSS-фиде оставляем только последние
MAX_FEED_ITEMS материалов (старые статьи остаются доступны по прямой
ссылке в docs/articles/, просто выпадают из фида — это нормально для RSS).
"""
import html
import os
import sys
from datetime import datetime
from email.utils import format_datetime

from utils import log, load_json, save_json, state_path, DOCS_DIR, pages_base_url

PENDING_FILE = state_path("pending.json")
POSTED_FILE = state_path("posted.json")
ARTICLES_STATE_FILE = state_path("dzen_articles.json")
ARTICLES_DIR = DOCS_DIR / "articles"
FEED_FILE = DOCS_DIR / "dzen.xml"

MAX_FEED_ITEMS = 100
MAX_TITLE_LEN = 100


def make_title(text: str, date_iso: str) -> str:
    stripped = (text or "").strip()
    first_line = stripped.splitlines()[0] if stripped else ""
    if first_line:
        if len(first_line) > MAX_TITLE_LEN:
            first_line = first_line[:MAX_TITLE_LEN].rsplit(" ", 1)[0] + "…"
        return first_line
    return f"Пост от {date_iso[:10]}"


def render_media_html(media: list) -> str:
    parts = []
    for m in media:
        url = html.escape(m["public_url"])
        if m["type"] == "photo":
            parts.append(f'<p><img src="{url}" alt="" style="max-width:100%;height:auto;"></p>')
        elif m["type"] == "video":
            parts.append(
                f'<p><video src="{url}" controls style="max-width:100%;height:auto;"></video></p>'
            )
    return "\n".join(parts)


def render_article_html(title: str, text: str, media: list, date_iso: str) -> str:
    body_text = "\n".join(
        f"<p>{html.escape(line)}</p>"
        for line in (text or "").strip().splitlines()
        if line.strip()
    )
    media_html = render_media_html(media)
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
</head>
<body>
<article>
<h1>{safe_title}</h1>
<time datetime="{date_iso}">{date_iso[:10]}</time>
{media_html}
{body_text}
</article>
</body>
</html>
"""


def build_rss(articles: list) -> str:
    base_url = pages_base_url()
    items_xml = []

    for a in articles[:MAX_FEED_ITEMS]:
        link = f"{base_url}/articles/{a['id']}.html"
        pub_date = format_datetime(datetime.fromisoformat(a["date"]))
        text = a.get("text", "") or a["title"]
        summary = html.escape(text[:300])
        content_html = render_article_html(a["title"], text, a.get("media", []), a["date"])

        enclosure = ""
        media = a.get("media", [])
        if media:
            first = media[0]
            mime = "image/jpeg" if first["type"] == "photo" else "video/mp4"
            length = 0
            try:
                length = os.path.getsize(first["local_path"])
            except OSError:
                pass
            enclosure = (
                f'\n      <enclosure url="{html.escape(first["public_url"])}" '
                f'length="{length}" type="{mime}"/>'
            )

        items_xml.append(f"""    <item>
      <title>{html.escape(a['title'])}</title>
      <link>{link}</link>
      <guid isPermaLink="false">{html.escape(a['id'])}</guid>
      <pubDate>{pub_date}</pubDate>
      <description>{summary}</description>
      <content:encoded><![CDATA[{content_html}]]></content:encoded>{enclosure}
    </item>""")

    items_joined = "\n".join(items_xml)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Asya Omnia — блог</title>
    <link>{base_url}/</link>
    <description>Автоматический RSS-фид для импорта в Дзен</description>
    <language>ru</language>
{items_joined}
  </channel>
</rss>
"""


def main():
    pending = load_json(PENDING_FILE, [])
    posted = load_json(POSTED_FILE, {})
    articles = load_json(ARTICLES_STATE_FILE, [])
    known_ids = {a["id"] for a in articles}

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    new_count = 0
    for item in pending:
        entry = posted.setdefault(item["id"], {})
        dzen_state = entry.setdefault("dzen", {"done": False})

        if dzen_state["done"] or item["id"] in known_ids:
            dzen_state["done"] = True
            continue

        title = make_title(item.get("text", ""), item["date"])
        media = item.get("media", [])
        article_html = render_article_html(title, item.get("text", ""), media, item["date"])

        article_path = ARTICLES_DIR / f"{item['id']}.html"
        with open(article_path, "w", encoding="utf-8") as f:
            f.write(article_html)

        articles.append({
            "id": item["id"],
            "title": title,
            "date": item["date"],
            "text": item.get("text", ""),
            "media": media,
        })
        known_ids.add(item["id"])
        dzen_state["done"] = True
        new_count += 1

    articles.sort(key=lambda a: a["date"], reverse=True)
    articles = articles[:MAX_FEED_ITEMS]

    FEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        f.write(build_rss(articles))

    save_json(ARTICLES_STATE_FILE, articles)
    save_json(POSTED_FILE, posted)

    log(f"Дзен: новых статей добавлено {new_count}. Всего в фиде: {len(articles)}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ОШИБКА update_dzen_feed: {e}")
        sys.exit(1)
        
