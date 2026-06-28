"""/start — приветствие + кнопки «Попробовать» и «Промокод» (BOT_PLAN.md §1)."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from ..config import Config
from ..db import Database
from .. import texts
from ..keyboards import kb_after_key, kb_start

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, config: Config) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    user = await db.get_user(message.from_user.id)

    # Уже есть активный ключ → показываем ссылку + приложения.
    if user and user.sub_id and user.state in {"trial_active", "promo_active", "paid", "friends"}:
        await message.answer(
            texts.KEY_ALREADY.format(sub_link=config.sub_link(user.sub_id)),
            reply_markup=kb_after_key(),
        )
        return

    await message.answer(texts.WELCOME, reply_markup=kb_start())
