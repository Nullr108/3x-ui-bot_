"""Планировщик отложенных уведомлений (APScheduler).

Реализует сценарии BOT_PLAN.md §3 и §5.1:
- +4ч после выдачи триала: проверка трафика → оффер или планирование «−3ч»;
- за 3ч до конца триала: напоминание протестировать (если трафика так и нет);
- за 1 день до конца платной: уведомление о продлении.

Job id привязан к tg_id, чтобы джобы можно было отменять/перепланировать.
Jobstore — in-memory; при старте делаем rehydrate() из БД, чтобы пережить рестарт.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Config
from .db import Database
from . import texts
from .keyboards import kb_pay
from .xui import XUI

log = logging.getLogger(__name__)


def _job_check(tg_id: int) -> str:
    return f"check4h:{tg_id}"


def _job_remind(tg_id: int) -> str:
    return f"remind3h:{tg_id}"


def _job_paid(tg_id: int) -> str:
    return f"paid1d:{tg_id}"


class Scheduler:
    def __init__(self, bot: Bot, db: Database, xui: XUI, cfg: Config):
        self.bot = bot
        self.db = db
        self.xui = xui
        self.cfg = cfg
        self.sched = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        self.sched.start()

    # ── планирование ─────────────────────────────────────
    def schedule_trial_flow(self, tg_id: int) -> None:
        """После выдачи триала: запланировать проверку трафика через N часов."""
        run_at = datetime.now(timezone.utc) + timedelta(
            hours=self.cfg.check_traffic_after_hours
        )
        self.sched.add_job(
            self._check_trial_4h,
            "date",
            run_date=run_at,
            args=[tg_id],
            id=_job_check(tg_id),
            replace_existing=True,
        )
        log.info("scheduled check4h for %s at %s", tg_id, run_at)

    def _schedule_remind_3h(self, tg_id: int, trial_expiry_ms: int) -> None:
        run_at = datetime.fromtimestamp(
            trial_expiry_ms / 1000, tz=timezone.utc
        ) - timedelta(hours=self.cfg.remind_before_end_hours)
        if run_at <= datetime.now(timezone.utc):
            return  # уже поздно напоминать
        self.sched.add_job(
            self._remind_3h_before,
            "date",
            run_date=run_at,
            args=[tg_id],
            id=_job_remind(tg_id),
            replace_existing=True,
        )
        log.info("scheduled remind3h for %s at %s", tg_id, run_at)

    def schedule_paid_notify(self, tg_id: int, paid_until_ms: int) -> None:
        run_at = datetime.fromtimestamp(
            paid_until_ms / 1000, tz=timezone.utc
        ) - timedelta(days=self.cfg.notify_before_paid_end_days)
        if run_at <= datetime.now(timezone.utc):
            return
        self.sched.add_job(
            self._notify_1day_before,
            "date",
            run_date=run_at,
            args=[tg_id],
            id=_job_paid(tg_id),
            replace_existing=True,
        )
        log.info("scheduled paid1d for %s at %s", tg_id, run_at)

    def _cancel(self, job_id: str) -> None:
        job = self.sched.get_job(job_id)
        if job:
            job.remove()

    def _cancel_user_jobs(self, tg_id: int) -> None:
        for jid in (_job_check(tg_id), _job_remind(tg_id), _job_paid(tg_id)):
            self._cancel(jid)

    # ── периодическая синхронизация с панелью ────────────
    def schedule_sync(self) -> None:
        """Раз в N минут сверять БД бота с панелью (удалённые вручную клиенты)."""
        self.sched.add_job(
            self.sync_clients,
            "interval",
            minutes=self.cfg.sync_interval_minutes,
            id="sync_clients",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
        )
        log.info("client sync scheduled every %d min", self.cfg.sync_interval_minutes)

    async def sync_clients(self) -> tuple[int, int]:
        """Если клиент пропал из панели — сбрасываем юзера в боте (pipeline заново).

        Возвращает (проверено, сброшено). На сетевых/сессионных ошибках юзера
        НЕ трогаем (сброс только при подтверждённом отсутствии клиента)."""
        users = await self.db.all_users()
        checked = reset = 0
        for u in users:
            if not u.client_email or u.state not in {"trial_active", "promo_active", "paid", "friends"}:
                continue
            checked += 1
            try:
                status = await self.xui.get_status(u.client_email)
            except Exception as e:  # noqa: BLE001
                log.warning("sync: status check failed for %s: %s", u.client_email, e)
                continue
            if status is None:
                await self.db.reset_user(u.tg_id)
                self._cancel_user_jobs(u.tg_id)
                reset += 1
                log.info(
                    "sync: %s gone from panel → reset user %s", u.client_email, u.tg_id
                )
        log.info("sync done: checked=%d, reset=%d", checked, reset)
        return checked, reset

    # ── джобы ────────────────────────────────────────────
    async def _check_trial_4h(self, tg_id: int) -> None:
        user = await self.db.get_user(tg_id)
        if not user or not user.client_email or user.paid:
            return
        status = await self.xui.get_status(user.client_email)
        if status is None:
            return

        if status.traffic_used:
            # Трафик использовался → оффер оплаты
            await self.bot.send_message(
                tg_id,
                texts.OFFER_AFTER_USE.format(price=self.cfg.price_rub),
                reply_markup=kb_pay(),
            )
            self._cancel(_job_remind(tg_id))
        else:
            # Трафика нет → планируем напоминание за 3ч до конца
            if user.trial_expiry_ms:
                self._schedule_remind_3h(tg_id, user.trial_expiry_ms)

    async def _remind_3h_before(self, tg_id: int) -> None:
        user = await self.db.get_user(tg_id)
        if not user or not user.client_email or user.paid:
            return
        status = await self.xui.get_status(user.client_email)
        if status is None:
            return

        if status.traffic_used:
            await self.bot.send_message(
                tg_id,
                texts.OFFER_AFTER_USE.format(price=self.cfg.price_rub),
                reply_markup=kb_pay(),
            )
        else:
            await self.bot.send_message(
                tg_id,
                texts.REMIND_TEST.format(
                    hours=self.cfg.remind_before_end_hours,
                    sub_link=self.cfg.sub_link(user.sub_id or ""),
                    price=self.cfg.price_rub,
                ),
                reply_markup=kb_pay(),
            )

    async def _notify_1day_before(self, tg_id: int) -> None:
        user = await self.db.get_user(tg_id)
        if not user or not user.client_email:
            return
        status = await self.xui.get_status(user.client_email)
        until_ms = status.expiry_time if status else (user.paid_until_ms or 0)
        await self.bot.send_message(
            tg_id,
            texts.PAID_ENDING_SOON.format(
                until=texts.fmt_date_ms(until_ms), price=self.cfg.price_rub
            ),
            reply_markup=kb_pay(),
        )

    # ── восстановление после рестарта ────────────────────
    async def rehydrate(self) -> None:
        """Пересоздать актуальные джобы из БД (jobstore in-memory не переживает рестарт)."""
        now_ms = int(time.time() * 1000)
        cur = await self.db.conn.execute("SELECT * FROM users")
        rows = await cur.fetchall()
        for row in rows:
            d = dict(row)
            tg_id = d["tg_id"]
            if d.get("paid") and d.get("paid_until_ms"):
                if d["paid_until_ms"] > now_ms:
                    self.schedule_paid_notify(tg_id, d["paid_until_ms"])
            elif d.get("state") == "trial_active" and d.get("trial_expiry_ms"):
                if d["trial_expiry_ms"] > now_ms:
                    # упрощённо: повторно планируем проверку трафика + напоминание
                    issued = d.get("trial_issued_at") or 0
                    check_at = (issued + self.cfg.check_traffic_after_hours * 3600)
                    if check_at * 1000 > now_ms:
                        run_at = datetime.fromtimestamp(check_at, tz=timezone.utc)
                        self.sched.add_job(
                            self._check_trial_4h, "date", run_date=run_at,
                            args=[tg_id], id=_job_check(tg_id), replace_existing=True,
                        )
                    else:
                        self._schedule_remind_3h(tg_id, d["trial_expiry_ms"])
        log.info("scheduler rehydrated: %d users", len(rows))
