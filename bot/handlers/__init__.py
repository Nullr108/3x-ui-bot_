"""Регистрация всех роутеров в диспетчере."""
from __future__ import annotations

from aiogram import Dispatcher

from . import admin, info, payment, promo, receipt_handler, start, trial


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(start.router)
    dp.include_router(trial.router)
    dp.include_router(info.router)
    dp.include_router(admin.router)        # команды /selftest, /panel
    dp.include_router(payment.router)
    dp.include_router(receipt_handler.router)
    dp.include_router(promo.router)         # включает catch-all для текста (промокод)
