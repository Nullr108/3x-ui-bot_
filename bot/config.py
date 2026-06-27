"""Конфигурация бота из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


def _xui_token() -> str:
    """Bearer-токен 3x-ui. Игнорируем мусор: пустую строку или значение с не-ASCII
    (частая ошибка — в .env затащили комментарий-подсказку). Тогда работаем по логину/паролю."""
    val = (os.getenv("XUI_TOKEN") or "").strip()
    if not val:
        return ""
    if any(ord(ch) > 127 for ch in val):
        import logging
        logging.getLogger("bot.config").warning(
            "XUI_TOKEN содержит не-ASCII символы и проигнорирован — используется логин/пароль. "
            "Очисти XUI_TOKEN в .env, если не пользуешься bearer-токеном."
        )
        return ""
    return val


@dataclass(frozen=True)
class Config:
    # Telegram
    bot_token: str = field(default_factory=lambda: os.environ["BOT_TOKEN"])
    admin_ids: set[int] = field(default_factory=_admin_ids)

    # 3x-ui
    xui_host: str = field(default_factory=lambda: os.environ["XUI_HOST"])
    xui_username: str = field(default_factory=lambda: os.getenv("XUI_USERNAME", ""))
    xui_password: str = field(default_factory=lambda: os.getenv("XUI_PASSWORD", ""))
    xui_token: str = field(default_factory=_xui_token)
    xui_tls_verify: bool = field(default_factory=lambda: _bool("XUI_TLS_VERIFY", True))
    xui_panel_url: str = field(default_factory=lambda: os.getenv("XUI_PANEL_URL", ""))

    # Подписка / оплата
    sub_base: str = field(default_factory=lambda: os.getenv("SUB_BASE", "").rstrip("/"))
    payment_url: str = field(default_factory=lambda: os.getenv("PAYMENT_URL", ""))
    price_rub: int = field(default_factory=lambda: _int("PRICE_RUB", 200))

    # Промокод (возврат старых клиентов): ключ на N дней по секретному коду
    promo_code: str = field(default_factory=lambda: (os.getenv("PROMO_CODE") or "").strip())
    promo_days: int = field(default_factory=lambda: _int("PROMO_DAYS", 7))

    # Секретный код для друзей: безлимитный бессрочный ключ
    friends_code: str = field(default_factory=lambda: (os.getenv("FRIENDS_CODE") or "").strip())

    # Тайминги
    trial_days: int = field(default_factory=lambda: _int("TRIAL_DAYS", 1))
    trial_limit_ip: int = field(default_factory=lambda: _int("TRIAL_LIMIT_IP", 2))
    paid_days: int = field(default_factory=lambda: _int("PAID_DAYS", 30))
    check_traffic_after_hours: int = field(
        default_factory=lambda: _int("CHECK_TRAFFIC_AFTER_HOURS", 4)
    )
    remind_before_end_hours: int = field(
        default_factory=lambda: _int("REMIND_BEFORE_END_HOURS", 3)
    )
    notify_before_paid_end_days: int = field(
        default_factory=lambda: _int("NOTIFY_BEFORE_PAID_END_DAYS", 1)
    )
    sync_interval_minutes: int = field(
        default_factory=lambda: _int("SYNC_INTERVAL_MINUTES", 60)
    )

    # Прочее
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "bot.db"))

    def sub_link(self, sub_id: str) -> str:
        return f"{self.sub_base}/{sub_id}"

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


config = Config()
