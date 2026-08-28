"""
Шаг 4: публикуем новые посты в Threads через официальный Threads API
(graph.threads.net). Поддерживается только один медиа-файл на пост
(если в Telegram-посте несколько фото — в Threads уйдёт только первое,
полный набор будет в VK и Дзене). Посты без медиа публикуются как TEXT.

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


def truncate(text: str) -> str:
    if len(text) <= MAX_TEXT_LEN:
        return text
    return text[:MAX_TEXT_LEN].rsplit(" ", 1)[0] + "…"


def post_item(item: dict) -> bool:
    media = item.get("media", [])
    params = {"access_token": THREADS_TOKEN}

    text = truncate(item.get("text", ""))
    if text:
        params["text"] = text

    if media and media[0]["type"] == "photo":
        params["media_type"] = "IMAGE"
        params["image_url"] = media[0]["public_url"]
    elif media and media[0]["type"] == "video":
        params["media_type"] = "VIDEO"
        params["video_url"] = media[0]["public_url"]
    else:
        params["media_type"] = "TEXT"

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
    if "error" in r.json():
        raise RuntimeError(r.json()["error"])
    return True


def main():
    pending = load_json(PENDING_FILE, [])
    posted = load_json(POSTED_FILE, {})

    if not pending:
        log("Threads: нет новых постов для публикации.")
        return

    for item in pending:
        entry = posted.setdefault(item["id"], {})
        state = entry.setdefault("threads", {"done": False, "attempts": 0})

        if state["done"]:
            continue
        if state["attempts"] >= MAX_ATTEMPTS:
            log(f"Threads: пост {item['id']} пропущен — превышено число попыток ({MAX_ATTEMPTS}).")
            continue

        try:
            post_item(item)
            state["done"] = True
            log(f"Threads: пост {item['id']} опубликован.")
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
