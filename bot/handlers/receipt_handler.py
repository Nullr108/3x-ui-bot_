"""Приём PDF-чека → проверка → продление на месяц (BOT_PLAN.md §5)."""
from __future__ import annotations

import logging
import os
import tempfile

from aiogram import F, Router
from aiogram.types import Message

from ..config import Config
from ..db import Database
from .. import texts
from ..keyboards import kb_pay
from ..receipt import verify_receipt
from ..scheduler import Scheduler
from ..xui import XUI

log = logging.getLogger(__name__)
router = Router(name="receipt")


@router.message(F.document)
async def on_document(
    message: Message,
    db: Database,
    xui: XUI,
    scheduler: Scheduler,
    config: Config,
) -> None:
    user = await db.get_user(message.from_user.id)

    # Чек ждём только когда пользователь в сценарии оплаты.
    if not user or not user.awaiting_receipt:
        await message.answer(texts.RECEIPT_NOT_WAITING)
        return

    doc = message.document
    is_pdf = (doc.mime_type == "application/pdf") or (
        doc.file_name or ""
    ).lower().endswith(".pdf")
    if not is_pdf:
        await message.answer(texts.RECEIPT_BAD.format(price=config.price_rub))
        return

    await message.answer(texts.RECEIPT_WAIT)

    # Скачиваем во временный файл.
    tmp_dir = tempfile.mkdtemp(prefix="receipt_")
    pdf_path = os.path.join(tmp_dir, doc.file_name or "receipt.pdf")
    try:
        await message.bot.download(doc, destination=pdf_path)
        result = verify_receipt(pdf_path, config.price_rub)
    finally:
        try:
            os.remove(pdf_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass

    if not result.ok:
        log.info("receipt rejected for %s: %s", message.from_user.id, result.reason)
        await message.answer(texts.RECEIPT_BAD.format(price=config.price_rub))
        return

    # Защита от повторного использования чека.
    if result.fingerprint and await db.receipt_seen(result.fingerprint):
        await message.answer(texts.RECEIPT_DUPLICATE)
        return

    # Продлеваем на месяц.
    try:
        new_expiry_ms = await xui.extend(user.client_email, config.paid_days)
    except Exception:  # noqa: BLE001
        log.exception("extend failed")
        await message.answer(
            "Оплата принята, но не получилось продлить ключ автоматически. "
            "Напиши админу — продлим вручную."
        )
        return

    if result.fingerprint:
        await db.save_receipt(result.fingerprint, message.from_user.id)
    await db.set_fields(
        message.from_user.id,
        paid=1,
        paid_until_ms=new_expiry_ms,
        awaiting_receipt=0,
        state="paid",
    )

    await message.answer(
        texts.RECEIPT_OK.format(until=texts.fmt_date_ms(new_expiry_ms))
    )

    # Уведомление за день до конца платной подписки.
    scheduler.schedule_paid_notify(message.from_user.id, new_expiry_ms)
