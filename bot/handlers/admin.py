"""Админ: вход в UI 3x-ui (WebApp) + самотест всего пайплайна (BOT_PLAN.md §6)."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..config import Config
from ..db import Database
from .. import selftest, texts
from ..keyboards import kb_admin_panel
from ..scheduler import Scheduler
from ..xui import XUI

log = logging.getLogger(__name__)
router = Router(name="admin")


@router.message(Command("selftest", "check"))
async def cmd_selftest(
    message: Message, db: Database, xui: XUI, scheduler: Scheduler, config: Config
) -> None:
    if not config.is_admin(message.from_user.id):
        await message.answer(texts.NOT_ADMIN)
        return

    status_msg = await message.answer(
        "⏳ Запускаю самотест пайплайна (создание ключа → статус → смена email → "
        "продление → парсер чека → очистка → планировщик)…"
    )
    try:
        report = await selftest.run(
            bot=message.bot, db=db, xui=xui, scheduler=scheduler,
            config=config, admin_id=message.from_user.id,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("selftest crashed")
        await status_msg.edit_text(f"❌ Самотест упал с ошибкой:\n<code>{e}</code>")
        return

    await status_msg.edit_text(report)


@router.message(Command("sync"))
async def cmd_sync(message: Message, scheduler: Scheduler, config: Config) -> None:
    if not config.is_admin(message.from_user.id):
        await message.answer(texts.NOT_ADMIN)
        return
    checked, reset = await scheduler.sync_clients()
    await message.answer(
        f"🔄 Синхронизация с панелью завершена.\n"
        f"Проверено активных: <b>{checked}</b>\n"
        f"Сброшено (удалены из панели): <b>{reset}</b>"
    )


@router.message(Command("panel", "admin"))
async def cmd_panel(message: Message, config: Config) -> None:
    if not config.is_admin(message.from_user.id):
        await message.answer(texts.NOT_ADMIN)
        return

    if not config.xui_panel_url.startswith("https://"):
        await message.answer(
            "WebApp требует https. Укажи корректный XUI_PANEL_URL (https) в .env."
        )
        return

    await message.answer(
        texts.ADMIN_PANEL, reply_markup=kb_admin_panel(config.xui_panel_url)
    )
