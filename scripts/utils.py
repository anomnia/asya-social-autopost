"""
Общие утилиты: работа с состоянием (state/*.json), безопасное логирование
(чтобы токены никогда не попадали в лог — репозиторий публичный, а логи
GitHub Actions в публичном репозитории видны всем).
"""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
DOCS_DIR = ROOT / "docs"
MEDIA_DIR = DOCS_DIR / "media"

STATE_DIR.mkdir(exist_ok=True)
DOCS_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)

# Любые query-параметры вида access_token=... / token=... маскируем перед тем,
# как что-либо печатать в лог — на случай, если они попали в URL ошибки.
_TOKEN_RE = re.compile(r"(access_token|token)=[^&\s]+", re.IGNORECASE)


def safe(text) -> str:
    """Убрать из строки похожие на токены значения перед печатью в лог."""
    return _TOKEN_RE.sub(r"\1=***", str(text))


def log(*args):
    print(*[safe(a) for a in args], flush=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def state_path(name: str) -> Path:
    return STATE_DIR / name


def pages_base_url() -> str:
    """
    Публичный базовый URL GitHub Pages для этого репозитория,
    например https://anomnia.github.io/asya-social-autopost
    Берётся из переменной окружения PAGES_BASE_URL (задаётся в workflow
    на основе github.repository), чтобы не хардкодить.
    """
    url = os.environ.get("PAGES_BASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("PAGES_BASE_URL не задан")
    return url
