"""
Шаг 4: публикуем новые посты в Threads через официальный Threads API
(graph.threads.net). Длинный текст автоматически разбивается на ветку
(thread) из нескольких последовательных постов (root + reply'и), чтобы
ничего не обрезалось лимитом Threads в 500 символов. В конце каждой
ветки добавляется отдельный пост-реплай со ссылкой на Telegram-канал.

Поддерживается только один медиа-файл на пост (если в Telegram-посте
несколько фото — в Threads уйдёт только первое, полный набор будет в
VK и Дзене). Медиа прикрепляется только к первому посту ветки.

Важно: image_url/video_url должны быть уже доступны публично — этот
скрипт нужно запускать ПОСЛЕ того, как медиа закоммичено и запушено
в docs/, и GitHub Pages успело её отдать (см. wait_for_pages.py).
"""
import os
import sys
import time

import requests

from utils import log, load_json, save_json, state_path

THREADS_TOKEN = os.environ["THREADS_ACCESS_TOKEN"]
THREADS_USER_ID = os.environ["THREADS_USER_ID"]
API = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}"

PENDING_FILE = state_path("pending.json")
POSTED_FILE = state_path("posted.json")
MAX_ATTEMPTS = 5
MAX_TEXT_LEN = 480  # с запасом от лимита в 500 символов

TELEGRAM_CHANNEL_LINK = "https://t.me/hypnomnia"
PROMO_TEXT = (
    "В канале рассказываю больше о том, как обрести гармонию с собой, "
    "партнером, жизнью.\n" + TELEGRAM_CHANNEL_LINK
)


def split_into_chunks(text: str, limit: int = MAX_TEXT_LEN) -> list:
    """Разбить текст на части не длиннее limit символов, стараясь резать
    по границам абзацев, а внутри абзаца — по границам слов."""
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    current = ""

    def flush():
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue

        flush()

        if len(para) <= limit:
            current = para
            continue

        piece = ""
        for word in para.split(" "):
            candidate = f"{piece} {word}" if piece else word
            if len(candidate) <= limit:
                piece = candidate
            else:
                if piece:
                    chunks.append(piece)
                piece = word
        current = piece

    flush()
    return chunks


def publish_part(text: str, media_type: str = "TEXT", media_url_field: str = None,
                  media_url: str = None, reply_to_id: str = None) -> str:
    """Опубликовать один пост ветки (root или reply) и вернуть его id."""
    params = {"access_token": THREADS_TOKEN, "media_type": media_type}
    if text:
        params["text"] = text
    if media_url_field and media_url:
        params[media_url_field] = media_url
    if reply_to_id:
        params["reply_to_id"] = reply_to_id

    r = requests.post(f"{API}/threads", data=params, timeout=60)
    r.raise_for_status()
    creation_id = r.json()["id"]

    time.sleep(30)  # Meta рекомендует подождать перед публикацией контейнера

    r = requests.post(
        f"{API}/threads_publish",
        data={"creation_id": creation_id, "access_token": THREADS_TOKEN},
        timeout=60,
    )
    r.raise_for_status()
    result = r.json()
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["id"]


def post_item(item: dict, state: dict) -> None:
    """Опубликовать пост как ветку (root + продолжения + промо-реплай).
    Прогресс сохраняется в state["published_ids"], поэтому при повторной
    попытке после сбоя уже опубликованные части не дублируются."""
    media = item.get("media", [])
    parts = split_into_chunks(item.get("text", "")) or [""]
    parts.append(PROMO_TEXT)

    published_ids = state.setdefault("published_ids", [])
    start_index = len(published_ids)

    for idx in range(start_index, len(parts)):
        media_type = "TEXT"
        media_url_field = None
        media_url = None
        if idx == 0 and media:
            if media[0]["type"] == "photo":
                media_type = "IMAGE"
                media_url_field = "image_url"
                media_url = media[0]["public_url"]
            elif media[0]["type"] == "video":
                media_type = "VIDEO"
                media_url_field = "video_url"
                media_url = media[0]["public_url"]

        reply_to_id = published_ids[-1] if published_ids else None
        new_id = publish_part(
            parts[idx],
            media_type=media_type,
            media_url_field=media_url_field,
            media_url=media_url,
            reply_to_id=reply_to_id,
        )
        published_ids.append(new_id)


def main():
    pending = load_json(PENDING_FILE, [])
    posted = load_json(POSTED_FILE, {})

    if not pending:
        log("Threads: нет новых постов для публикации.")
        return

    for item in pending:
        entry = posted.setdefault(item["id"], {})
        state = entry.setdefault("threads", {"done": False, "attempts": 0, "published_ids": []})
        state.setdefault("published_ids", [])

        if state["done"]:
            continue
        if state["attempts"] >= MAX_ATTEMPTS:
            log(f"Threads: пост {item['id']} пропущен — превышено число попыток ({MAX_ATTEMPTS}).")
            continue

        try:
            post_item(item, state)
            state["done"] = True
            log(f"Threads: пост {item['id']} опубликован веткой из {len(state['published_ids'])} сообщений.")
        except Exception as e:
            state["attempts"] += 1
            log(f"Threads: ошибка публикации поста {item['id']} (попытка {state['attempts']}): {e}")

    save_json(POSTED_FILE, posted)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ОШИБКА post_threads: {e}")
        sys.exit(1)
