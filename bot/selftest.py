"""Админский самотест: автоматический прогон всего backend-пайплайна.

Создаёт одноразового тестового клиента, прогоняет все операции из BOT_PLAN.md
(создание → чтение → смена email → продление → парсер чека → очистка → планировщик),
выдаёт чеклист ✅/❌ и удаляет за собой. Реальный Telegram-флоу (кнопки) при этом
не трогается — это проверка «железа», чтобы понять, можно ли отдавать клиентам.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from aiogram import Bot

from .config import Config
from .db import Database
from . import receipt
from .scheduler import Scheduler
from .xui import XUI

log = logging.getLogger(__name__)


class _Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.passed = 0
        self.failed = 0

    def ok(self, name: str, detail: str = "") -> None:
        self.passed += 1
        self.lines.append(f"✅ {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, detail: str = "") -> None:
        self.failed += 1
        self.lines.append(f"❌ {name}" + (f" — {detail}" if detail else ""))

    def info(self, name: str, detail: str = "") -> None:
        self.lines.append(f"ℹ️ {name}" + (f" — {detail}" if detail else ""))

    def text(self) -> str:
        head = f"<b>Самотест</b>: {self.passed} ✅ / {self.failed} ❌\n\n"
        verdict = (
            "\n\n🟢 <b>Backend готов — можно отдавать клиентам.</b>"
            if self.failed == 0
            else "\n\n🔴 <b>Есть проблемы — смотри ❌ выше, отдавать рано.</b>"
        )
        return head + "\n".join(self.lines) + verdict


def _days_from_now(expiry_ms: int) -> float:
    return (expiry_ms - time.time() * 1000) / 86400000


async def run(
    bot: Bot, db: Database, xui: XUI, scheduler: Scheduler, config: Config, admin_id: int
) -> str:
    r = _Report()
    ts = int(time.time())
    email = f"selftest-{admin_id}-{ts}"
    email_renamed = f"selftest-renamed-{admin_id}-{ts}"
    active_email = email  # отслеживаем актуальный email для очистки
    sub_id: str | None = None

    # 1. Связь с панелью + инбаунды
    try:
        inbound_ids = await xui.list_inbound_ids()
        if inbound_ids:
            r.ok("Связь с 3x-ui / инбаунды", f"{len(inbound_ids)} шт: {inbound_ids}")
        else:
            r.fail("Связь с 3x-ui / инбаунды", "инбаундов нет — создать ключ некуда")
            return r.text()
    except Exception as e:  # noqa: BLE001
        r.fail("Связь с 3x-ui", str(e))
        return r.text()

    # 2. get_status несуществующего → None (регресс фикса record-not-found)
    try:
        none_st = await xui.get_status(f"nope-{ts}")
        if none_st is None:
            r.ok("Обработка «клиент не найден»", "вернулось None, как надо")
        else:
            r.fail("Обработка «клиент не найден»", "ожидался None")
    except Exception as e:  # noqa: BLE001
        r.fail("Обработка «клиент не найден»", str(e))

    # 3. Создание триал-клиента
    try:
        cid, sub_id, created_inbounds = await xui.create_trial(
            email=email, tg_id=admin_id, days=config.trial_days,
            limit_ip=config.trial_limit_ip,
        )
        r.ok("Создание триал-клиента", f"uuid={cid[:8]}…, инбаундов={len(created_inbounds)}")
    except Exception as e:  # noqa: BLE001
        r.fail("Создание триал-клиента", str(e))
        return r.text()

    # 4. Чтение статуса созданного
    try:
        st = await xui.get_status(email)
        if st is None:
            r.fail("Чтение статуса клиента", "клиент не найден после создания")
        else:
            checks = []
            checks.append(("enable", st.enable is True))
            checks.append((f"limit_ip={st.limit_ip}", st.limit_ip == config.trial_limit_ip))
            d = _days_from_now(st.expiry_time)
            checks.append((f"срок ~{d:.2f}д", 0 < d <= config.trial_days + 0.1))
            bad = [n for n, okk in checks if not okk]
            if bad:
                r.fail("Чтение статуса клиента", "не совпало: " + ", ".join(bad))
            else:
                r.ok("Чтение статуса клиента", ", ".join(n for n, _ in checks))
    except Exception as e:  # noqa: BLE001
        r.fail("Чтение статуса клиента", str(e))

    # 5. Ссылка на подписку (+ best-effort проверка доступности)
    link = config.sub_link(sub_id or "")
    if not config.sub_base:
        r.fail("Ссылка подписки", "SUB_BASE не задан в .env")
    else:
        try:
            verify = config.xui_tls_verify
            async with httpx.AsyncClient(verify=verify, timeout=8, follow_redirects=True) as c:
                resp = await c.get(link)
            body_len = len(resp.text)
            if resp.status_code == 200 and body_len > 0:
                r.ok("Ссылка подписки отвечает", f"HTTP 200, {body_len} симв.")
            else:
                r.info("Ссылка подписки", f"HTTP {resp.status_code}, {body_len} симв. — проверь формат SUB_BASE")
        except Exception as e:  # noqa: BLE001
            r.info("Ссылка подписки", f"не достучался ({e}) — проверь SUB_BASE/порт")

    # 6. Смена email (критичный username-гейт)
    try:
        ok = await xui.change_email(email, email_renamed)
        after_new = await xui.get_status(email_renamed)
        after_old = await xui.get_status(email)
        if ok and after_new is not None and after_old is None:
            active_email = email_renamed
            r.ok("Смена email клиента", f"{email} → {email_renamed}")
        else:
            r.fail(
                "Смена email клиента",
                f"ok={ok}, new={'есть' if after_new else 'нет'}, old={'остался' if after_old else 'удалён'}",
            )
            # если новый создался — чистим его тоже
            if after_new is not None:
                active_email = email_renamed
    except Exception as e:  # noqa: BLE001
        r.fail("Смена email клиента", str(e))

    # 7. Продление на месяц (имитация оплаты)
    try:
        before = await xui.get_status(active_email)
        before_ms = before.expiry_time if before else 0
        new_ms = await xui.extend(active_email, config.paid_days)
        added_days = (new_ms - before_ms) / 86400000
        if added_days >= config.paid_days - 0.1:
            r.ok("Продление (+месяц)", f"+{added_days:.1f}д, до {datetime.fromtimestamp(new_ms/1000, tz=timezone.utc):%d.%m.%Y}")
        else:
            r.fail("Продление (+месяц)", f"добавилось всего {added_days:.1f}д")
    except Exception as e:  # noqa: BLE001
        r.fail("Продление (+месяц)", str(e))

    # 8. Парсер чека (на образцах текста, без генерации PDF)
    try:
        good = receipt.analyze_text(
            f"Чек по операции 1234567\nПеревод выполнен успешно\n"
            f"Сумма {config.price_rub},00 руб\nПолучатель Иван И.",
            config.price_rub,
        )
        bad = receipt.analyze_text("Перевод 50 руб выполнен успешно", config.price_rub)
        if good.ok and good.amount == config.price_rub and not bad.ok:
            r.ok("Парсер чека", f"верный чек принят ({good.amount}₽), неверный отклонён")
        else:
            r.fail("Парсер чека", f"good.ok={good.ok}/{good.amount}, bad.ok={bad.ok}")
    except Exception as e:  # noqa: BLE001
        r.fail("Парсер чека", str(e))

    # 9. Очистка тестового клиента
    try:
        await xui.delete_client(active_email, inbound_ids)
        await xui.delete_client(email, inbound_ids)  # на случай, если смена email не прошла
        gone = await xui.get_status(active_email)
        if gone is None:
            r.ok("Очистка тестового клиента", "удалён со всех инбаундов")
        else:
            r.fail("Очистка тестового клиента", f"остался: {active_email}")
    except Exception as e:  # noqa: BLE001
        r.fail("Очистка тестового клиента", str(e))

    # 10. Планировщик: одноразовая задача через ~5 c пришлёт админу DM
    try:
        run_at = datetime.now(timezone.utc) + timedelta(seconds=5)
        scheduler.sched.add_job(
            _scheduler_ping, "date", run_date=run_at,
            args=[bot, admin_id], id=f"selftest_ping:{admin_id}", replace_existing=True,
        )
        r.ok("Планировщик", "задача через 5 c запланирована (придёт ⏰-сообщение)")
    except Exception as e:  # noqa: BLE001
        r.fail("Планировщик", str(e))

    # 11. Конфиг для оплаты / админки
    cfg_problems = []
    if not config.payment_url:
        cfg_problems.append("PAYMENT_URL пуст")
    if not config.xui_panel_url.startswith("https://"):
        cfg_problems.append("XUI_PANEL_URL не https (WebApp не откроется)")
    if not config.admin_ids:
        cfg_problems.append("ADMIN_IDS пуст")
    if cfg_problems:
        r.fail("Конфиг оплаты/админки", "; ".join(cfg_problems))
    else:
        r.ok("Конфиг оплаты/админки", f"цена {config.price_rub}₽, админов {len(config.admin_ids)}")

    return r.text()


async def _scheduler_ping(bot: Bot, admin_id: int) -> None:
    await bot.send_message(
        admin_id,
        "⏰ Планировщик сработал — отложенные уведомления (4ч/3ч/1день) будут приходить.",
    )
