"""
Шаг 1: забираем новые посты из Telegram-канала через Bot API (long polling
через getUpdates + сохранённый offset — бот должен быть добавлен в канал
администратором, тогда посты приходят как update.channel_post).

Ничего никуда не публикует. Результат:
  - state/telegram_offset.json — обновлённый offset
  - state/pending.json — список новых постов для публикации
  - docs/media/<group>/... — скачанные фото/видео (публикуются через
    GitHub Pages, поэтому кладём их в docs/)
"""
import os
import sys
import time
from datetime import datetime, timezone

import requests

from utils import log, load_json, save_json, state_path, MEDIA_DIR, pages_base_url

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]  # например -1001234567890 или @channel_username
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

OFFSET_FILE = state_path("telegram_offset.json")
PENDING_FILE = state_path("pending.json")


def chat_matches(chat: dict) -> bool:
    if CHANNEL_ID.lstrip("-").isdigit():
        return str(chat.get("id")) == CHANNEL_ID
    uname = CHANNEL_ID.lstrip("@").lower()
    return (chat.get("username") or "").lower() == uname


def tg_get(method, **params):
    r = requests.get(f"{API}/{method}", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error in {method}: {data.get('description')}")
    return data["result"]


def download_file(file_id: str, dest_dir, filename: str) -> str:
    info = tg_get("getFile", file_id=file_id)
    file_path = info["file_path"]
    url = f"{FILE_API}/{file_path}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    dest_dir.mkdir(parents=True, exist_ok=True)
    full_path = dest_dir / filename
    with open(full_path, "wb") as f:
        f.write(r.content)
    return str(full_path)


def main():
    state = load_json(OFFSET_FILE, {"offset": 0})
    offset = state.get("offset", 0)

    updates = tg_get(
        "getUpdates",
        offset=offset,
        timeout=0,
        allowed_updates='["channel_post"]',
    )

    if not updates:
        log("Новых обновлений из Telegram нет.")
        save_json(PENDING_FILE, [])
        return

    max_update_id = offset - 1
    groups = {}  # group_key -> list of messages (in order)

    for upd in updates:
        max_update_id = max(max_update_id, upd["update_id"])
        msg = upd.get("channel_post")
        if not msg:
            continue
        if not chat_matches(msg.get("chat", {})):
            continue
        group_key = str(msg.get("media_group_id") or msg["message_id"])
        groups.setdefault(group_key, []).append(msg)

    pending = []

    for group_key, msgs in groups.items():
        msgs.sort(key=lambda m: m["message_id"])
        text = ""
        for m in msgs:
            text = m.get("caption") or m.get("text") or text
        first_msg_id = msgs[0]["message_id"]
        dest_dir = MEDIA_DIR / group_key
        media_items = []

        for m in msgs:
            if "photo" in m:
                largest = max(m["photo"], key=lambda p: p.get("file_size", 0))
                fname = f"{m['message_id']}.jpg"
                local_path = download_file(largest["file_id"], dest_dir, fname)
                media_items.append({
                    "type": "photo",
                    "local_path": local_path,
                    "public_url": f"{pages_base_url()}/media/{group_key}/{fname}",
                })
            elif "video" in m:
                v = m["video"]
                fname = f"{m['message_id']}.mp4"
                local_path = download_file(v["file_id"], dest_dir, fname)
                media_items.append({
                    "type": "video",
                    "local_path": local_path,
                    "public_url": f"{pages_base_url()}/media/{group_key}/{fname}",
                })

        if not text and not media_items:
            continue

        date_ts = msgs[0].get("date", int(time.time()))
        pending.append({
            "id": group_key,
            "tg_message_id": first_msg_id,
            "date": datetime.fromtimestamp(date_ts, tz=timezone.utc).isoformat(),
            "text": text,
            "media": media_items,
        })

    save_json(PENDING_FILE, pending)
    save_json(OFFSET_FILE, {"offset": max_update_id + 1})
    log(f"Новых постов к публикации: {len(pending)}. Новый offset: {max_update_id + 1}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ОШИБКА fetch_telegram: {e}")
        sys.exit(1)
