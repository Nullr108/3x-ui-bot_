"""«Оплатить» + гейт по username (BOT_PLAN.md §4).

Логика:
- «Оплатить»: если username нет (или email ещё temp-) → инструкция + кнопка
  «Username установлен». Иначе → сценарий оплаты.
- «Username установлен»: перечитать username; если есть — сменить email клиента
  в 3x-ui и только потом запустить сценарий оплаты.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..config import Config
from ..db import Database
from .. import texts
from ..keyboards import (
    CB_PAY,
    CB_USERNAME_DONE,
    kb_pay_link,
    kb_username_done,
)
from ..xui import XUI
from .common import is_temp_email

log = logging.getLogger(__name__)
router = Router(name="payment")


async def _start_payment_flow(callback: CallbackQuery, db: Database, config: Config) -> None:
    """Сценарий оплаты (BOT_PLAN.md §4.3): ссылка + ожидание чека."""
    await db.set_fields(callback.from_user.id, awaiting_receipt=1, awaiting_username=0)
    await callback.message.answer(
        texts.PAY_INSTRUCTIONS.format(
            price=config.price_rub, payment_url=config.payment_url
        ),
        reply_markup=kb_pay_link(config.payment_url),
    )


@router.callback_query(F.data == CB_PAY)
async def on_pay(callback: CallbackQuery, db: Database, config: Config) -> None:
    await callback.answer()
    tg = callback.from_user
    await db.ensure_user(tg.id, tg.username)
    user = await db.get_user(tg.id)

    username_ok = bool(tg.username) and not is_temp_email(
        user.client_email if user else None
    )

    if username_ok:
        await _start_payment_flow(callback, db, config)
        return

    # Username нет / email ещё temp- → ведём на установку username.
    if user:
        await db.set_fields(tg.id, awaiting_username=1)
    await callback.message.answer(
        texts.USERNAME_REQUIRED, reply_markup=kb_username_done()
    )


@router.callback_query(F.data == CB_USERNAME_DONE)
async def on_username_done(
    callback: CallbackQuery, db: Database, xui: XUI, config: Config
) -> None:
    await callback.answer()
    tg = callback.from_user
    user = await db.get_user(tg.id)

    # username всё ещё не появился → повторяем инструкцию.
    if not tg.username:
        await callback.message.answer(
            texts.USERNAME_STILL_EMPTY, reply_markup=kb_username_done()
        )
        return

    new_email = "@" + tg.username

    # Если клиента ещё нет (юзер не брал триал) — просто фиксируем username.
    if user and user.client_email and user.client_email != new_email:
        ok = await xui.change_email(user.client_email, new_email)
        if not ok:
            await callback.message.answer(
                "Не удалось обновить данные в системе 😕 Попробуй позже или напиши админу."
            )
            return

    await db.set_fields(
        tg.id,
        client_email=new_email,
        tg_username=tg.username,
        awaiting_username=0,
    )
    await callback.message.answer(texts.USERNAME_OK)

    # Только после успешного обновления email — запускаем оплату.
    await _start_payment_flow(callback, db, config)
