"""Локальная БД (SQLite) для бизнес-состояния воронки.

В 3x-ui хранится только сам VPN-ключ. Здесь — этап воронки, флаги, тайминги,
привязка tg_id → client_email/uuid/sub_id и анти-дубликат чеков.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id           INTEGER PRIMARY KEY,
    tg_username     TEXT,
    client_email    TEXT,            -- текущий email клиента в 3x-ui (= ключ)
    client_uuid     TEXT,            -- client.id, для update/delete
    inbound_ids     TEXT,            -- CSV id инбаундов, куда добавлен клиент
    sub_id          TEXT,
    trial_issued_at INTEGER,         -- unix-секунды
    trial_expiry_ms INTEGER,         -- unix-мс
    paid_until_ms   INTEGER,
    state           TEXT DEFAULT 'new',  -- new|trial_active|promo_active|paid
    awaiting_username INTEGER DEFAULT 0,
    awaiting_receipt  INTEGER DEFAULT 0,
    awaiting_promo    INTEGER DEFAULT 0,
    paid              INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS receipts (
    fingerprint TEXT PRIMARY KEY,    -- хэш/номер операции — защита от повторного чека
    tg_id       INTEGER,
    created_at  INTEGER
);
"""


@dataclass
class User:
    tg_id: int
    tg_username: str | None = None
    client_email: str | None = None
    client_uuid: str | None = None
    inbound_ids: str | None = None
    sub_id: str | None = None
    trial_issued_at: int | None = None
    trial_expiry_ms: int | None = None
    paid_until_ms: int | None = None
    state: str = "new"
    awaiting_username: int = 0
    awaiting_receipt: int = 0
    awaiting_promo: int = 0
    paid: int = 0

    @property
    def inbound_id_list(self) -> list[int]:
        if not self.inbound_ids:
            return []
        return [int(x) for x in self.inbound_ids.split(",") if x]


class Database:
    def __init__(self, path: str):
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        """Лёгкие миграции для уже существующих БД (ADD COLUMN если отсутствует)."""
        cur = await self._conn.execute("PRAGMA table_info(users)")
        cols = {row["name"] for row in await cur.fetchall()}
        if "awaiting_promo" not in cols:
            await self._conn.execute(
                "ALTER TABLE users ADD COLUMN awaiting_promo INTEGER DEFAULT 0"
            )

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "DB not connected"
        return self._conn

    # ── users ────────────────────────────────────────────
    async def get_user(self, tg_id: int) -> User | None:
        cur = await self.conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return User(**dict(row)) if row else None

    async def ensure_user(self, tg_id: int, tg_username: str | None = None) -> None:
        """Гарантирует наличие строки пользователя (иначе set_fields/UPDATE — no-op).

        Создаёт минимальную запись, если её нет, и освежает username."""
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (tg_id, tg_username, state) VALUES (?, ?, 'new')",
            (tg_id, tg_username),
        )
        if tg_username is not None:
            await self.conn.execute(
                "UPDATE users SET tg_username = ? WHERE tg_id = ?", (tg_username, tg_id)
            )
        await self.conn.commit()

    async def all_users(self) -> list[User]:
        cur = await self.conn.execute("SELECT * FROM users")
        return [User(**dict(r)) for r in await cur.fetchall()]

    async def reset_user(self, tg_id: int) -> None:
        """Сброс юзера в состояние 'new' (клиент пропал из панели) —
        чтобы он мог заново пройти pipeline. tg_id/tg_username сохраняем."""
        await self.set_fields(
            tg_id,
            client_email=None,
            client_uuid=None,
            inbound_ids=None,
            sub_id=None,
            trial_issued_at=None,
            trial_expiry_ms=None,
            paid_until_ms=None,
            state="new",
            awaiting_username=0,
            awaiting_receipt=0,
            awaiting_promo=0,
            paid=0,
        )

    async def upsert_user(self, user: User) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (tg_id, tg_username, client_email, client_uuid,
                inbound_ids, sub_id, trial_issued_at, trial_expiry_ms, paid_until_ms,
                state, awaiting_username, awaiting_receipt, awaiting_promo, paid)
            VALUES (:tg_id, :tg_username, :client_email, :client_uuid,
                :inbound_ids, :sub_id, :trial_issued_at, :trial_expiry_ms, :paid_until_ms,
                :state, :awaiting_username, :awaiting_receipt, :awaiting_promo, :paid)
            ON CONFLICT(tg_id) DO UPDATE SET
                tg_username=excluded.tg_username,
                client_email=excluded.client_email,
                client_uuid=excluded.client_uuid,
                inbound_ids=excluded.inbound_ids,
                sub_id=excluded.sub_id,
                trial_issued_at=excluded.trial_issued_at,
                trial_expiry_ms=excluded.trial_expiry_ms,
                paid_until_ms=excluded.paid_until_ms,
                state=excluded.state,
                awaiting_username=excluded.awaiting_username,
                awaiting_receipt=excluded.awaiting_receipt,
                awaiting_promo=excluded.awaiting_promo,
                paid=excluded.paid
            """,
            user.__dict__,
        )
        await self.conn.commit()

    async def set_fields(self, tg_id: int, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self.conn.execute(
            f"UPDATE users SET {cols} WHERE tg_id = ?",
            (*fields.values(), tg_id),
        )
        await self.conn.commit()

    # ── receipts (анти-дубль) ────────────────────────────
    async def receipt_seen(self, fingerprint: str) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM receipts WHERE fingerprint = ?", (fingerprint,)
        )
        return await cur.fetchone() is not None

    async def save_receipt(self, fingerprint: str, tg_id: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO receipts (fingerprint, tg_id, created_at) VALUES (?, ?, ?)",
            (fingerprint, tg_id, int(time.time())),
        )
        await self.conn.commit()
