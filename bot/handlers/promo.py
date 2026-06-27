"""Кнопка «Промокод» — ключ на 7 дней для возвращающихся клиентов.

Поток: «Промокод» → (нужен username) → ввод секретного кода → выдача ключа.
Код задаётся в .env (PROMO_CODE), срок — PROMO_DAYS.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..db import Database
from .. import texts
from ..keyboards import CB_PROMO, CB_PROMO_USERNAME_DONE, kb_promo_username_done
from ..keyflow import issue_key
from ..scheduler import Scheduler
from ..xui import XUI

log = logging.getLogger(__name__)
router = Router(name="promo")


async def _ask_code(callback: CallbackQuery, db: Database) -> None:
    await db.set_fields(callback.from_user.id, awaiting_promo=1, awaiting_username=0)
    await callback.message.answer(texts.PROMO_ASK_CODE)


@router.callback_query(F.data == CB_PROMO)
async def on_promo(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    tg = callback.from_user

    # Промокод требует username (ключ создаётся сразу как @username).
    if not tg.username:
        await callback.message.answer(
            texts.USERNAME_REQUIRED_PROMO, reply_markup=kb_promo_username_done()
        )
        return

    await _ask_code(callback, db)


@router.callback_query(F.data == CB_PROMO_USERNAME_DONE)
async def on_promo_username_done(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    tg = callback.from_user
    if not tg.username:
        await callback.message.answer(
            texts.USERNAME_STILL_EMPTY, reply_markup=kb_promo_username_done()
        )
        return
    await db.set_fields(tg.id, tg_username=tg.username)
    await callback.message.answer(texts.USERNAME_OK)
    await _ask_code(callback, db)


@router.message(F.text & ~F.text.startswith("/"))
async def on_promo_code(
    message: Message,
    db: Database,
    xui: XUI,
    scheduler: Scheduler,
    config: Config,
) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or not user.awaiting_promo:
        return  # не в режиме ввода промокода — игнорируем обычный текст

    code = (message.text or "").strip().lower()

    # Секретный код для друзей → безлимитный бессрочный ключ.
    if config.friends_code and code == config.friends_code.lower():
        await db.set_fields(message.from_user.id, awaiting_promo=0)
        await message.answer(texts.FRIENDS_WELCOME)
        await issue_key(
            bot=message.bot, db=db, xui=xui, scheduler=scheduler, config=config,
            tg=message.from_user, days=0, state="friends",
            limit_ip=0, schedule_funnel=False,
        )
        return

    # Обычный промокод → ключ на PROMO_DAYS дней.
    if config.promo_code and code == config.promo_code.lower():
        await db.set_fields(message.from_user.id, awaiting_promo=0)
        await message.answer(texts.PROMO_WELCOME_BACK.format(days=config.promo_days))
        await issue_key(
            bot=message.bot, db=db, xui=xui, scheduler=scheduler, config=config,
            tg=message.from_user, days=config.promo_days, state="promo_active",
        )
        return

    await message.answer(texts.PROMO_BAD_CODE)
