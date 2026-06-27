"""Кнопка «Попробовать» — выдача триал-клиента на 1 день (BOT_PLAN.md §2)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..config import Config
from ..db import Database
from ..keyboards import CB_TRIAL
from ..keyflow import issue_key
from ..scheduler import Scheduler
from ..xui import XUI

log = logging.getLogger(__name__)
router = Router(name="trial")


@router.callback_query(F.data == CB_TRIAL)
async def on_trial(
    callback: CallbackQuery,
    db: Database,
    xui: XUI,
    scheduler: Scheduler,
    config: Config,
) -> None:
    await callback.answer()
    await issue_key(
        bot=callback.bot, db=db, xui=xui, scheduler=scheduler, config=config,
        tg=callback.from_user, days=config.trial_days, state="trial_active",
    )
