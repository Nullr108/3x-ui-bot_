"""Общая выдача ключа клиенту (используется триалом и промокодом).

Создаёт клиента в 3x-ui (или переиспользует существующего), сохраняет состояние
в БД, шлёт подробную инструкцию с кнопками приложений и запускает сценарий
отложенных уведомлений.
"""
from __future__ import annotations

import logging
import time

from aiogram import Bot

from .config import Config
from .db import Database, User
from . import texts
from .keyboards import kb_after_key
from .scheduler import Scheduler
from .util import build_email
from .xui import XUI

log = logging.getLogger(__name__)


# Состояния, при которых у юзера уже есть рабочий ключ
ACTIVE_STATES = {"trial_active", "promo_active", "paid", "friends"}


async def issue_key(
    bot: Bot,
    db: Database,
    xui: XUI,
    scheduler: Scheduler,
    config: Config,
    tg,
    days: int,
    state: str,
    *,
    limit_ip: int | None = None,
    schedule_funnel: bool = True,
) -> bool:
    """Выдаёт клиенту ключ на `days` дней (days<=0 → бессрочный).

    limit_ip=None → берём триальный лимит; 0 → без лимита устройств.
    schedule_funnel=False → не запускаем напоминалки/офферы (для друзей).
    Возвращает True при успехе.
    """
    chat_id = tg.id
    email = build_email(tg)
    if limit_ip is None:
        limit_ip = config.trial_limit_ip

    user = await db.get_user(tg.id)
    # Уже есть активный ключ → просто отдаём его.
    if user and user.sub_id and user.state in ACTIVE_STATES:
        await bot.send_message(
            chat_id,
            texts.KEY_ALREADY.format(sub_link=config.sub_link(user.sub_id)),
            reply_markup=kb_after_key(config.sub_link(user.sub_id)),
        )
        return True

    # Анти-дубликат на стороне панели.
    existing = await xui.get_status(email)
    if existing is not None and existing.sub_id:
        cid, sub_id, inbound_ids = existing.uuid, existing.sub_id, []
        expiry_ms = existing.expiry_time
    else:
        try:
            cid, sub_id, inbound_ids = await xui.create_trial(
                email=email, tg_id=tg.id, days=days, limit_ip=limit_ip
            )
        except Exception:  # noqa: BLE001
            log.exception("issue_key: create failed")
            await bot.send_message(
                chat_id, "Не получилось создать ключ 😕 Попробуй позже или напиши админу."
            )
            return False
        expiry_ms = int((time.time() + days * 86400) * 1000) if days > 0 else 0

    await db.upsert_user(
        User(
            tg_id=tg.id,
            tg_username=tg.username,
            client_email=email,
            client_uuid=cid,
            inbound_ids=",".join(map(str, inbound_ids)),
            sub_id=sub_id,
            trial_issued_at=int(time.time()),
            trial_expiry_ms=expiry_ms,
            state=state,
        )
    )

    await bot.send_message(
        chat_id,
        texts.KEY_ISSUED.format(sub_link=config.sub_link(sub_id)),
        reply_markup=kb_after_key(config.sub_link(sub_id)),
    )
    if schedule_funnel:
        scheduler.schedule_trial_flow(tg.id)
    return True
