"""Кнопки приложений (Android/iOS со ссылками на магазины) и «Как подключиться»."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from .. import texts
from ..keyboards import CB_APPS_ANDROID, CB_APPS_IOS, CB_HOWTO, kb_apps

router = Router(name="info")


@router.callback_query(F.data == CB_APPS_IOS)
async def on_apps_ios(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(texts.APPS_IOS, reply_markup=kb_apps("ios"))


@router.callback_query(F.data == CB_APPS_ANDROID)
async def on_apps_android(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(texts.APPS_ANDROID, reply_markup=kb_apps("android"))


@router.callback_query(F.data == CB_HOWTO)
async def on_howto(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(texts.HOWTO)
