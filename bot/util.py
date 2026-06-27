"""Мелкие утилиты без зависимостей от хендлеров (чтобы не было циклических импортов)."""
from __future__ import annotations

from aiogram.types import User as TgUser


def build_email(tg_user: TgUser) -> str:
    """email клиента в 3x-ui: @username либо temp-<id> (BOT_PLAN.md §0)."""
    if tg_user.username:
        return "@" + tg_user.username
    return f"temp-{tg_user.id}"


def is_temp_email(email: str | None) -> bool:
    return bool(email) and email.startswith("temp-")
