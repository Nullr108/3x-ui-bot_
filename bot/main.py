"""Точка входа: связывает Telegram (aiogram), 3x-ui (py3xui), БД и планировщик."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

if __package__ is None:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramServerError

from bot.config import config
from bot.db import Database
from bot.handlers import register_handlers
from bot.scheduler import Scheduler
from bot.xui import XUI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# Сетевые ошибки доступа к api.telegram.org, которые надо переживать ретраями
NET_ERRORS = (TelegramNetworkError, TelegramServerError, OSError)


async def _preflight(bot: Bot) -> None:
    """Дождаться доступности Telegram API. bot.me() кэширует результат,
    поэтому последующий start_polling не будет дёргать сеть на старте."""
    backoff = 5
    while True:
        try:
            me = await bot.me()
            log.info("Telegram доступен: @%s", me.username)
            return
        except NET_ERRORS as e:
            log.warning(
                "Telegram недоступен (%s). Повтор через %d с. "
                "Если повторяется — проверь сеть/прокси или запусти бота на сервере.",
                e, backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def _resilient_polling(dp: Dispatcher, bot: Bot) -> None:
    """Запускает polling и перезапускает его при сетевых обрывах."""
    backoff = 5
    while True:
        try:
            await _preflight(bot)
            await dp.start_polling(bot, handle_signals=False)
            return  # штатная остановка (Ctrl+C обработан снаружи)
        except NET_ERRORS as e:
            log.warning("Polling оборвался (%s). Перезапуск через %d с.", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def main() -> None:
    # 1. 3x-ui
    xui = XUI(config)
    await xui.login()

    # 2. БД
    db = Database(config.db_path)
    await db.connect()

    # 3. Бот + диспетчер
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # 4. Планировщик
    scheduler = Scheduler(bot, db, xui, config)

    # 5. Внедрение зависимостей в хендлеры (aiogram прокидывает по имени параметра)
    dp["db"] = db
    dp["xui"] = xui
    dp["scheduler"] = scheduler
    dp["config"] = config

    register_handlers(dp)

    # 6. Старт планировщика + восстановление джоб + периодическая синхронизация
    scheduler.start()
    await scheduler.rehydrate()
    scheduler.schedule_sync()

    log.info("Bot started")
    try:
        await _resilient_polling(dp, bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
