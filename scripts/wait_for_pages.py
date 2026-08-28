"""
Шаг 3: после того как медиа запушено в docs/, ждём, пока GitHub Pages
отдаст его по публичному URL (обычно 30-90 секунд, у первого деплоя может
быть дольше). Threads не примет image_url/video_url, который ещё недоступен.
"""
import sys
import time

import requests

from utils import log, load_json, state_path

PENDING_FILE = state_path("pending.json")
TIMEOUT_SECONDS = 180
POLL_INTERVAL = 10


def main():
    pending = load_json(PENDING_FILE, [])
    urls = [m["public_url"] for item in pending for m in item.get("media", [])]

    if not urls:
        log("Нет медиа для ожидания публикации на GitHub Pages.")
        return

    deadline = time.time() + TIMEOUT_SECONDS
    remaining = set(urls)

    while remaining and time.time() < deadline:
        for url in list(remaining):
            try:
                r = requests.head(url, timeout=10, allow_redirects=True)
                if r.status_code == 200:
                    remaining.discard(url)
            except requests.RequestException:
                pass
        if remaining:
            time.sleep(POLL_INTERVAL)

    if remaining:
        log(f"ВНИМАНИЕ: {len(remaining)} медиафайлов не стали доступны за {TIMEOUT_SECONDS}с. "
            f"Публикация в Threads для соответствующих постов может не пройти в этот раз "
            f"и повторится в следующем запуске.")
    else:
        log("Все медиафайлы доступны на GitHub Pages.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ОШИБКА wait_for_pages: {e}")
        sys.exit(1)
