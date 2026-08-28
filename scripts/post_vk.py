"""
Шаг 2: публикуем новые посты (из state/pending.json) на стену группы VK.
Идемпотентно: то, что уже успешно опубликовано, отмечается в
state/posted.json и повторно не публикуется. Если пост не публикуется
после нескольких попыток подряд, помечаем как failed и не блокируем
остальные посты.
"""
import os
import sys

import requests

from utils import log, load_json, save_json, state_path

VK_TOKEN = os.environ["VK_ACCESS_TOKEN"]
VK_GROUP_ID = os.environ["VK_GROUP_ID"].lstrip("-")  # без минуса
API_VERSION = "5.199"
API = "https://api.vk.com/method"

PENDING_FILE = state_path("pending.json")
POSTED_FILE = state_path("posted.json")
MAX_ATTEMPTS = 5


def vk_call(method, **params):
    params["access_token"] = VK_TOKEN
    params["v"] = API_VERSION
    r = requests.post(f"{API}/{method}", data=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"VK error {data['error'].get('error_code')}: {data['error'].get('error_msg')}")
    return data["response"]


def upload_photo(local_path: str) -> str:
    upload_info = vk_call("photos.getWallUploadServer", group_id=VK_GROUP_ID)
    with open(local_path, "rb") as f:
        r = requests.post(upload_info["upload_url"], files={"photo": f}, timeout=120)
    r.raise_for_status()
    upload_result = r.json()
    saved = vk_call(
        "photos.saveWallPhoto",
        group_id=VK_GROUP_ID,
        photo=upload_result["photo"],
        server=upload_result["server"],
        hash=upload_result["hash"],
    )
    photo = saved[0]
    return f"photo{photo['owner_id']}_{photo['id']}"


def upload_video(local_path: str, name: str) -> str:
    save_info = vk_call("video.save", group_id=VK_GROUP_ID, name=name, wallpost=0)
    with open(local_path, "rb") as f:
        r = requests.post(save_info["upload_url"], files={"video_file": f}, timeout=300)
    r.raise_for_status()
    return f"video{save_info['owner_id']}_{save_info['video_id']}"


def post_item(item: dict) -> bool:
    attachments = []
    for media in item.get("media", []):
        if media["type"] == "photo":
            attachments.append(upload_photo(media["local_path"]))
        elif media["type"] == "video":
            title = (item.get("text") or "Видео")[:100]
            attachments.append(upload_video(media["local_path"], title))

    vk_call(
        "wall.post",
        owner_id=f"-{VK_GROUP_ID}",
        from_group=1,
        message=item.get("text", ""),
        attachments=",".join(attachments),
    )
    return True


def main():
    pending = load_json(PENDING_FILE, [])
    posted = load_json(POSTED_FILE, {})

    if not pending:
        log("VK: нет новых постов для публикации.")
        return

    for item in pending:
        entry = posted.setdefault(item["id"], {})
        vk_state = entry.setdefault("vk", {"done": False, "attempts": 0})

        if vk_state["done"]:
            continue
        if vk_state["attempts"] >= MAX_ATTEMPTS:
            log(f"VK: пост {item['id']} пропущен — превышено число попыток ({MAX_ATTEMPTS}).")
            continue

        try:
            post_item(item)
            vk_state["done"] = True
            log(f"VK: пост {item['id']} опубликован.")
        except Exception as e:
            vk_state["attempts"] += 1
            log(f"VK: ошибка публикации поста {item['id']} (попытка {vk_state['attempts']}): {e}")

    save_json(POSTED_FILE, posted)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ОШИБКА post_vk: {e}")
        sys.exit(1)
