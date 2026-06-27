"""Обёртка над 3x-ui (py3xui AsyncApi).

Инкапсулирует все операции с панелью, нужные боту по BOT_PLAN.md:
- создать триал-клиента на всех инбаундах;
- прочитать статус/трафик клиента;
- сменить email клиента (username → @username);
- продлить подписку после оплаты.

Держим ОДИН объект на всё приложение + авто-релогин при протухшей сессии
(шпаргалка §8).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from py3xui import AsyncApi, Client

from .config import Config

log = logging.getLogger(__name__)


def _is_record_not_found(e: Exception) -> bool:
    """На некоторых версиях панели get_by_email для отсутствующего клиента
    возвращает success=false «record not found», и py3xui кидает ValueError
    вместо None. Это логическая ситуация, а не сбой сессии."""
    return "record not found" in str(e).lower()


@dataclass
class ClientStatus:
    email: str
    enable: bool
    expiry_time: int           # unix-мс, 0 = бессрочно
    up: int
    down: int
    total_gb: int
    limit_ip: int
    uuid: str
    sub_id: str

    @property
    def used_bytes(self) -> int:
        return (self.up or 0) + (self.down or 0)

    @property
    def traffic_used(self) -> bool:
        return self.used_bytes > 0

    @property
    def expired(self) -> bool:
        return self.expiry_time != 0 and self.expiry_time < int(time.time() * 1000)


class XUI:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        if cfg.xui_token:
            self.api = AsyncApi(
                cfg.xui_host, token=cfg.xui_token, use_tls_verify=cfg.xui_tls_verify
            )
            self._use_token = True
        else:
            self.api = AsyncApi(
                cfg.xui_host,
                cfg.xui_username,
                cfg.xui_password,
                use_tls_verify=cfg.xui_tls_verify,
            )
            self._use_token = False

    async def login(self) -> None:
        if not self._use_token:
            await self.api.login()
            log.info("3x-ui: logged in")

    async def _retry(self, coro_factory):
        """Выполнить операцию; при ошибке сессии — релогин и повтор (шпаргалка §8).

        Логические ответы панели (напр. «record not found») не лечатся релогином —
        пробрасываем сразу, чтобы вызывающий код их обработал."""
        try:
            return await coro_factory()
        except Exception as e:  # noqa: BLE001 — SDK кидает разные типы
            if _is_record_not_found(e):
                raise
            log.warning("3x-ui call failed (%s), relogin & retry", e)
            await self.login()
            return await coro_factory()

    async def _raw_post(self, endpoint: str, data: dict) -> None:
        """Сырой POST к панели через авторизованную сессию py3xui.

        Нужен для «классических» эндпоинтов inbounds/... (шпаргалка §6), которых
        нет в обёртке py3xui или которые на этой версии панели работают только так."""
        base = self.api.client  # наследует _url/_post/cookies/_generate_headers
        url = base._url(endpoint)
        await self._retry(
            lambda: base._post(url, {"Accept": "application/json"}, data)
        )

    # ── чтение ───────────────────────────────────────────
    async def _get_client(self, email: str) -> Client | None:
        """get_by_email с обработкой «record not found» → None."""
        try:
            return await self._retry(lambda: self.api.client.get_by_email(email))
        except Exception as e:  # noqa: BLE001
            if _is_record_not_found(e):
                return None
            raise

    async def get_status(self, email: str) -> ClientStatus | None:
        c = await self._get_client(email)
        if c is None:
            return None
        return ClientStatus(
            email=c.email,
            enable=c.enable,
            expiry_time=c.expiry_time or 0,
            up=c.up or 0,
            down=c.down or 0,
            total_gb=c.total_gb or 0,
            limit_ip=c.limit_ip or 0,
            uuid=c.id,
            sub_id=c.sub_id or "",
        )

    async def list_inbound_ids(self) -> list[int]:
        inbounds = await self._retry(lambda: self.api.inbound.get_list())
        return [ib.id for ib in inbounds]

    # ── создание триала ──────────────────────────────────
    async def create_trial(
        self, email: str, tg_id: int, days: int, limit_ip: int
    ) -> tuple[str, str, list[int]]:
        """Создаёт клиента на ВСЕХ инбаундах с одним sub_id.

        Возвращает (client_uuid, sub_id, inbound_ids).
        """
        inbound_ids = await self.list_inbound_ids()
        if not inbound_ids:
            raise RuntimeError("В панели нет ни одного инбаунда")

        cid = str(uuid.uuid4())
        sub_id = uuid.uuid4().hex[:16]
        # days<=0 → бессрочный ключ (expiry 0); иначе конкретная дата
        expiry_ms = int((time.time() + days * 86400) * 1000) if days > 0 else 0

        for ib_id in inbound_ids:
            client = Client(
                id=cid,
                email=email,
                enable=True,
                expiry_time=expiry_ms,
                total_gb=0,            # безлимит по трафику — ограничение только по времени
                limit_ip=limit_ip,
                sub_id=sub_id,
                tg_id=tg_id,
            )
            await self._retry(lambda ib=ib_id, cl=client: self.api.client.add(ib, [cl]))

        log.info("trial created: email=%s inbounds=%s", email, inbound_ids)
        return cid, sub_id, inbound_ids

    @staticmethod
    def _client_uuid(c: Client) -> str:
        """Реальный VLESS-UUID строкой.

        На этой панели get_by_email кладёт UUID в поле `uuid`, а `id` = числовой
        DB-id (напр. 8). В запросах клиента нужен именно `uuid`."""
        return str(c.uuid or c.id or "")

    async def _update_client(
        self,
        lookup_email: str,
        *,
        new_email: str | None = None,
        expiry_time: int | None = None,
        enable: bool | None = None,
    ) -> bool:
        """Обновляет клиента через документированный POST clients/update/{email}.

        ВАЖНО (из api-docs панели): в пути — ТЕКУЩИЙ email, тело — ПОЛНЫЙ набор полей
        (сервер заменяет строку, не патчит), а `id` = строковый UUID (не числовой DB-id).
        """
        c = await self._get_client(lookup_email)
        if c is None:
            return False
        cid = self._client_uuid(c)
        if not cid:
            log.warning("_update_client: empty uuid for %s", lookup_email)
            return False

        body = {
            "email": new_email if new_email is not None else c.email,
            "enable": enable if enable is not None else c.enable,
            "id": cid,  # строковый UUID, не c.id(=число)
            "expiryTime": expiry_time if expiry_time is not None else (c.expiry_time or 0),
            "totalGB": c.total_gb or 0,
            "limitIp": c.limit_ip or 0,
            "subId": c.sub_id or "",
            "tgId": c.tg_id if c.tg_id is not None else "",
            "flow": c.flow or "",
        }
        # email в пути может содержать @ — это ок (так же работает clients/get/@user)
        await self._raw_post(f"panel/api/clients/update/{lookup_email}", body)
        return True

    # ── смена email (username → @username) ────────────────
    async def change_email(self, old_email: str, new_email: str) -> bool:
        """Меняет email клиента, сохраняя uuid/sub_id/срок/лимиты.

        POST clients/update/{old_email} с новым email в теле (api-docs панели).
        UUID и sub_id не трогаем — ссылка подписки и импортированный конфиг живут.
        """
        ok = await self._update_client(old_email, new_email=new_email)
        if not ok:
            log.warning("change_email: client %s not found", old_email)
            return False
        result = await self.get_status(new_email) is not None
        log.info("change_email %s -> %s: %s", old_email, new_email, "OK" if result else "FAIL")
        return result

    # ── удаление клиента (для очистки/самотеста) ─────────
    async def delete_client(
        self, email: str, inbound_ids: list[int] | None = None
    ) -> None:
        """Удаляет клиента по email через документированный
        POST clients/del/{email}?keepTraffic=0 (снимает со всех инбаундов)."""
        try:
            await self._raw_post(f"panel/api/clients/del/{email}?keepTraffic=0", {})
        except Exception as e:  # noqa: BLE001
            if _is_record_not_found(e):
                return
            log.warning("delete_client %s failed: %s", email, e)

    # ── продление после оплаты ───────────────────────────
    async def extend(self, email: str, add_days: int) -> int:
        """Продлевает от max(сейчас, текущий срок) на add_days. Возвращает новый expiry_ms."""
        c = await self._get_client(email)
        if c is None:
            raise RuntimeError(f"client {email} not found")
        now_ms = int(time.time() * 1000)
        base = c.expiry_time if (c.expiry_time and c.expiry_time > now_ms) else now_ms
        new_expiry = base + add_days * 86400000
        ok = await self._update_client(email, expiry_time=new_expiry, enable=True)
        if not ok:
            raise RuntimeError(f"extend failed for {email}")
        log.info("extended %s +%dd -> %d", email, add_days, new_expiry)
        return new_expiry
