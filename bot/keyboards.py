"""Inline-клавиатуры. callback_data согласованы с BOT_PLAN.md."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

# callback_data константы
CB_TRIAL = "trial"
CB_PROMO = "promo"
CB_PAY = "pay"
CB_USERNAME_DONE = "username_done"
CB_PROMO_USERNAME_DONE = "promo_username_done"
CB_APPS_IOS = "apps_ios"
CB_APPS_ANDROID = "apps_android"
CB_HOWTO = "howto"

# ── Приложения, поддерживающие подписочную ссылку ────────
# Порядок: сначала самые простые (для не-технических пользователей).
IOS_APPS: list[tuple[str, str]] = [
    ("Happ ⭐ проще всего", "https://apps.apple.com/app/id6504287215"),
    ("V2Box", "https://apps.apple.com/app/id6446814690"),
    ("V2RayTun", "https://apps.apple.com/app/id6476628951"),
    ("Streisand", "https://apps.apple.com/app/id6450534064"),
    ("Shadowrocket (платное)", "https://apps.apple.com/app/id932747118"),
    ("NPV Tunnel", "https://apps.apple.com/app/id1629465476"),
    ("Incy", "https://apps.apple.com/app/id6756943388"),
]

ANDROID_APPS: list[tuple[str, str]] = [
    ("Happ ⭐ проще всего", "https://play.google.com/store/apps/details?id=com.happproxy"),
    ("V2Box", "https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box"),
    ("V2RayTun", "https://play.google.com/store/apps/details?id=com.v2raytun.android"),
    ("V2RayNG", "https://play.google.com/store/apps/details?id=com.v2ray.ang"),
    ("Sing-box", "https://play.google.com/store/apps/details?id=io.nekohasekai.sfa"),
    ("NPV Tunnel", "https://play.google.com/store/apps/details?id=com.napsternetlabs.napsternetv"),
    ("Incy", "https://play.google.com/store/apps/details?id=llc.itdev.incy"),
]


def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Попробовать бесплатно", callback_data=CB_TRIAL)],
            [InlineKeyboardButton(text="🎟 У меня есть промокод", callback_data=CB_PROMO)],
        ]
    )


def kb_after_key() -> InlineKeyboardMarkup:
    """Кнопки под выданным ключом: магазины приложений + помощь."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Приложения для Android", callback_data=CB_APPS_ANDROID)],
            [InlineKeyboardButton(text="🍏 Приложения для iPhone (iOS)", callback_data=CB_APPS_IOS)],
            [InlineKeyboardButton(text="❓ Как подключиться — по шагам", callback_data=CB_HOWTO)],
        ]
    )


def kb_apps(platform: str) -> InlineKeyboardMarkup:
    """Список приложений-ссылок на магазин для платформы ('ios'|'android')."""
    apps = IOS_APPS if platform == "ios" else ANDROID_APPS
    rows = [[InlineKeyboardButton(text=name, url=url)] for name, url in apps]
    rows.append([InlineKeyboardButton(text="❓ Как подключиться", callback_data=CB_HOWTO)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_pay() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить", callback_data=CB_PAY)]]
    )


def kb_username_done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Username установлен", callback_data=CB_USERNAME_DONE)]
        ]
    )


def kb_promo_username_done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Username установлен", callback_data=CB_PROMO_USERNAME_DONE)]
        ]
    )


def kb_pay_link(payment_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)]]
    )


def kb_admin_panel(panel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔧 Открыть 3x-ui", web_app=WebAppInfo(url=panel_url))]
        ]
    )
