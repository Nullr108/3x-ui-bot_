# Шпаргалка: управление панелью 3X-UI через Python (для ИИ-агента и человека)

> Назначение файла: справочник по API панели **3X-UI** (форк MHSanaei, актуальная версия)
> для написания Telegram-бота (продажник / напоминатель / приём оплаты).
> Здесь — только про работу с API. Логику бота обсуждаем отдельно.

---

## 0. Краткая суть

3X-UI — это веб-панель для управления Xray (VLESS/VMess/Trojan/Shadowsocks и т.д.).
У неё есть HTTP API под путём `/panel/api/...`. Управлять им из Python можно двумя способами:

1. **Через готовый SDK `py3xui`** (рекомендуется) — объектная обёртка, sync и async.
2. **Напрямую через `requests`/`httpx`** — если нужен полный контроль или метода нет в SDK.

Для бота 90% задач закрывает `py3xui`. Сырые запросы держим в уме как запасной вариант.

Полезные ссылки:
- SDK: https://github.com/iwatkot/py3xui  (PyPI: `pip install py3xui`)
- Postman-документация API: https://documenter.getpostman.com/view/16802678/2s9YkgD5jm
- Панель 3x-ui: https://github.com/MHSanaei/3x-ui
- В самой панели есть встроенный Swagger: пункт **API Docs** в меню; OpenAPI-схема: `<host>/panel/api/openapi.json`

---

## 1. Установка и подключение

```bash
pip install py3xui
```

`py3xui` тянет `requests` (sync) и `httpx` (async) сам.

### Переменные окружения (рекомендуемый способ хранения кредов)

```python
import os
os.environ["XUI_HOST"]     = "https://panel.example.com:2053"  # с http(s):// и портом
os.environ["XUI_USERNAME"] = "admin"
os.environ["XUI_PASSWORD"] = "your-password"
os.environ["XUI_TOKEN"]    = ""  # опционально, см. раздел про токен
```

> ВАЖНО: `XUI_HOST` — это базовый URL панели **без** хвоста `/panel`.
> Если панель открыта по адресу с base-path (например `/abcXYZ/panel/`),
> то его надо включить в host: `https://panel.example.com:2053/abcXYZ`.

### Создание клиента API

```python
from py3xui import Api          # синхронный
# from py3xui import AsyncApi   # асинхронный — те же методы, но await

api = Api.from_env()            # читает XUI_HOST / XUI_USERNAME / XUI_PASSWORD
# или явно:
api = Api("https://panel.example.com:2053", "admin", "your-password")

api.login()                     # логинимся, получаем cookie сессии
```

Доп. параметры конструктора `Api(...)`:
- `use_tls_verify: bool = True` — проверка TLS-сертификата (для самоподписанного ставь `False`).
- `custom_certificate_path: str | None` — путь к своему CA-сертификату.
- `token: str | None` — bearer-токен (тогда `login()` не нужен).
- `logger` — свой логгер.
- `api.max_retries = 3` — число ретраев при сетевых ошибках.

### Async-вариант

```python
import asyncio
from py3xui import AsyncApi

async def main():
    api = AsyncApi.from_env()
    await api.login()
    inbounds = await api.inbound.get_list()
    print(inbounds)

asyncio.run(main())
```

Все методы ниже одинаковы для `Api` и `AsyncApi`, только в async их надо `await`-ить.
Для Telegram-бота (aiogram/aiohttp) бери **AsyncApi**.

---

## 2. Аутентификация

### Логин по паролю (основной способ)
```python
api.login()              # обычный вход
api.login("123456")      # если включена 2FA — передаём 6-значный код
```
Под капотом: получает CSRF-токен с `GET /csrf-token`, потом `POST /login`,
сохраняет cookie сессии. Cookie живёт ограниченное время → при долгой работе бота
лови ошибку и делай `api.login()` повторно (см. раздел «Хелперы»).

### Логин по bearer-токену (если в панели создан API-токен)
```python
api = Api("https://panel.example.com:2053", token="ВАШ_ТОКЕН")
# login() вызывать НЕ нужно; токен уходит в заголовке Authorization: Bearer ...
```
Токен создаётся в панели (Settings) — удобно для серверного бота, не протухает как сессия.

---

## 3. Модель данных `Client` (самое важное для бота)

`from py3xui import Client`. Это pydantic-модель. Поля (snake_case в Python, alias = имя в API):

| Python-поле   | API-ключ      | Тип            | Назначение |
|---------------|---------------|----------------|------------|
| `email`       | `email`       | str (обяз.)    | **Уникальное имя клиента** внутри inbound. Используется как ID во многих запросах. Часто туда кладут tg_id или метку. |
| `enable`      | `enable`      | bool (обяз.)   | Включён/выключен. `False` = доступ отрезан, но клиент не удалён. |
| `id`          | `id`          | int/str        | **UUID клиента** (для VLESS/VMess) или пароль (Trojan). Генерится `str(uuid.uuid4())`. |
| `password`    | `password`    | str            | Пароль (для протоколов, где он нужен, напр. Shadowsocks/Trojan). |
| `inbound_id`  | `inboundId`   | int            | К какому inbound привязан клиент. |
| `up`          | `up`          | int            | Отдано байт (статистика, read-only). |
| `down`        | `down`        | int            | Принято байт (статистика, read-only). |
| `total`       | `total`       | int            | Суммарный трафик (статистика). |
| `expiry_time` | `expiryTime`  | int            | **Срок действия**. Unix-время в **миллисекундах**. `0` = бессрочно. Отрицательное значение = относительный срок (мс от первого подключения). См. ниже. |
| `total_gb`    | `totalGB`     | int            | **Лимит трафика в БАЙТАХ** (не в ГБ, несмотря на имя!). `0` = безлимит. Чтобы 50 ГБ → `50 * 1024**3`. |
| `limit_ip`    | `limitIp`     | int            | Лимит одновременных IP/устройств. `0` = без лимита. |
| `sub_id`      | `subId`       | str            | ID подписки → ссылка `https://host/sub/<subId>`. |
| `tg_id`       | `tgId`        | int/str        | Telegram ID клиента (для привязки и уведомлений из панели). |
| `flow`        | `flow`        | str            | Flow для VLESS (напр. `xtls-rprx-vision`). |
| `method`      | `method`      | str            | Шифрование (для Shadowsocks). |
| `comment`     | `comment`     | str            | Произвольный комментарий. |
| `reset`       | `reset`       | int            | Когда последний раз сбрасывался трафик. |

### ⚠️ Критичные нюансы единиц измерения
- **`expiry_time` — в миллисекундах**, не в секундах!
  ```python
  import time
  # бессрочно
  expiry = 0
  # конкретная дата (через 30 дней от сейчас):
  expiry = int((time.time() + 30*24*3600) * 1000)
  # относительный срок «30 дней с первого коннекта»: отрицательное число мс
  expiry = -(30*24*3600*1000)
  ```
- **`total_gb` — в байтах**: `total_gb = 100 * 1024**3` → лимит 100 ГБ.
- Чтобы прочитать остаток трафика клиента: `остаток = total_gb - (up + down)` (если `total_gb > 0`).

---

## 4. Модель `Inbound`

`from py3xui import Inbound`. Inbound — это «точка входа» (порт + протокол + настройки),
внутри которой живут клиенты. Для бота-продажника обычно есть **уже созданный inbound**,
и бот просто добавляет/меняет клиентов внутри него. Создавать inbound'ы — реже.

Ключевые поля: `enable`, `port`, `protocol`, `settings`, `stream_settings`, `sniffing`,
`remark` (название), `id`, `up`/`down`/`total` (статистика), `expiry_time`,
`client_stats` (список `Client` со статистикой по каждому клиенту), `tag`.

`client_stats` — удобно: в нём по каждому клиенту видно `up`, `down`, `total`, `expiry_time`, `enable`.

---

## 5. Методы API

Все вызовы — после `api.login()` (или с токеном).

### 5.1 Клиенты — `api.client.*`

```python
# Получить клиента по email (главный способ узнать инфу о клиенте)
client = api.client.get_by_email("user@tg")          # -> Client | None
# В client: enable, expiry_time, total_gb, up, down, id(uuid), sub_id, tg_id ...

# Список IP, с которых заходил клиент
ips = api.client.get_ips("user@tg")                  # -> list[str]

# Добавить одного/несколько клиентов в inbound (id инбаунда!)
import uuid
new_client = Client(
    id=str(uuid.uuid4()),
    email="user@tg",
    enable=True,
    total_gb=50 * 1024**3,                            # 50 ГБ
    expiry_time=int((time.time() + 30*86400)*1000),  # +30 дней
    limit_ip=2,
    tg_id=123456789,
    sub_id="user_sub_id",
)
api.client.add(inbound_id=1, clients=[new_client])

# Обновить клиента (продлить, сменить лимит, включить/выключить...)
client = api.client.get_by_email("user@tg")
client.enable = True
client.expiry_time = int((time.time() + 60*86400)*1000)  # продлили на 60 дней
client.total_gb = 100 * 1024**3
api.client.update(client.id, client)                 # 1-й арг — UUID клиента (client.id)

# Сбросить список IP клиента (снять привязку устройств)
api.client.reset_ips("user@tg")

# Сбросить счётчик трафика клиента
api.client.reset_stats(inbound_id=1, email="user@tg")

# Удалить клиента (нужен id инбаунда и UUID клиента)
client = api.client.get_by_email("user@tg")
api.client.delete(inbound_id=1, client_uuid=client.id)

# Удалить всех «исчерпавших» клиентов в inbound (истёк срок/трафик)
api.client.delete_depleted(inbound_id=1)

# Кто сейчас онлайн (список email)
online_emails = api.client.online()                  # -> list[str]

# Трафик/инфо по UUID (без email)
clients = api.client.get_traffic_by_id("239708ef-487e-4945-829d-ad79a0ce067e")
```

> ⚠️ Тонкости реализации SDK:
> - `update(client_uuid, client)` — первый аргумент это UUID (`client.id`).
> - `delete(inbound_id, client_uuid)` — внутри SDK сам резолвит UUID → email; можно передать и email напрямую.
> - `reset_stats(inbound_id, email)` — endpoint сброса трафика по email.

### 5.2 Inbound'ы — `api.inbound.*`

```python
inbounds = api.inbound.get_list()          # -> list[Inbound]  (все инбаунды + клиенты)
inbound  = api.inbound.get_by_id(1)        # -> Inbound        (один инбаунд)

api.inbound.add(inbound)                   # создать новый inbound
api.inbound.update(1, inbound)             # обновить inbound по id
api.inbound.delete(1)                      # удалить inbound

api.inbound.reset_stats()                  # обнулить трафик ВСЕХ инбаундов
api.inbound.reset_client_stats(1)          # обнулить трафик клиентов инбаунда
```

Чтобы узнать `inbound_id`, к которому добавлять клиентов:
```python
for ib in api.inbound.get_list():
    print(ib.id, ib.remark, ib.protocol, ib.port)
```

### 5.3 Сервер — `api.server.*`

```python
status  = api.server.get_status()                  # CPU/RAM/сеть/аптайм -> Server
api.server.get_db("backup.db")                     # скачать бэкап БД в файл
keys    = api.server.generate_reality_keys()       # новая пара ключей Reality (X25519)
api.server.install_new_xray_version("1.8.0")       # обновить Xray
api.server.update_geofile()                         # обновить geoip/geosite
ver     = api.server.get_xray_version()            # версия Xray -> list[str]
cfg     = api.server.get_server_config()           # текущий конфиг Xray
```

### 5.4 База данных — `api.database.*`

```python
api.database.export()   # триггерит бэкап и отправку его админам в Telegram-бот панели
```

---

## 6. Сырые HTTP-эндпоинты (запасной вариант / если метода нет в SDK)

База: `<host>/panel/api/...`. Авторизация — cookie сессии (после `POST /login`)
или заголовок `Authorization: Bearer <token>`. Все «действия» — `POST`, чтения — `GET`/`POST`.
Ответ всегда в виде `{"success": bool, "msg": str, "obj": <данные>}`.

| Действие                         | Метод | Endpoint |
|----------------------------------|-------|----------|
| CSRF-токен                       | GET   | `/csrf-token` |
| Логин                            | POST  | `/login` (body: `username`, `password`, опц. `twoFactorCode`, заголовок `X-CSRF-Token`) |
| Список инбаундов                 | GET   | `/panel/api/inbounds/list` |
| Инбаунд по id                    | GET   | `/panel/api/inbounds/get/{id}` |
| Добавить инбаунд                 | POST  | `/panel/api/inbounds/add` |
| Обновить инбаунд                 | POST  | `/panel/api/inbounds/update/{id}` |
| Удалить инбаунд                  | POST  | `/panel/api/inbounds/del/{id}` |
| Сброс трафика всех инбаундов     | POST  | `/panel/api/inbounds/resetAllTraffics` |
| Инфо о клиенте по email          | GET   | `/panel/api/inbounds/getClientTraffics/{email}` *(в SDK через `clients/get`)* |
| Клиент по email (SDK)            | GET   | `/panel/api/clients/get/{email}` |
| IP клиента                       | POST  | `/panel/api/clients/ips/{email}` |
| Добавить клиента                 | POST  | `/panel/api/clients/add` (body: `{"client": {...}, "inboundIds": [id]}`) |
| Обновить клиента                 | POST  | `/panel/api/clients/update/{email|uuid}` |
| Очистить IP клиента              | POST  | `/panel/api/clients/clearIps/{email}` |
| Сброс трафика клиента            | POST  | `/panel/api/clients/resetTraffic/{email}` |
| Сброс трафика клиентов инбаунда  | POST  | `/panel/api/clients/resetAllTraffics` |
| Удалить клиента                  | POST  | `/panel/api/clients/del/{email}` |
| Удалить исчерпавших клиентов     | POST  | `/panel/api/clients/delDepleted` |
| Кто онлайн                       | POST  | `/panel/api/clients/onlines` |
| Список всех клиентов             | GET   | `/panel/api/clients/list` |
| Статус сервера                   | GET   | `/panel/api/server/status` |
| Скачать БД                       | GET   | `/panel/api/server/getDb` |
| Новые Reality-ключи              | GET   | `/panel/api/server/getNewX25519Cert` |
| Версия Xray                      | GET   | `/panel/api/server/getXrayVersion` |
| Конфиг сервера                   | GET   | `/panel/api/server/getConfigJson` |
| Бэкап в TG-бот                   | POST  | `/panel/api/backuptotgbot` |

> Примечание: в классической ветке 3x-ui многие операции с клиентами привязаны к inbound и шли через
> `/panel/api/inbounds/addClient`, `/panel/api/inbounds/updateClient/{uuid}`,
> `/panel/api/inbounds/{id}/delClient/{uuid}`, `/panel/api/inbounds/getClientTraffics/{email}`.
> SDK `py3xui` использует более новые пути `/panel/api/clients/...`. Если на твоей версии панели
> новый путь вернёт 404 — переключись на `inbounds/...`-варианты. **Проверяй на своей версии.**

### Пример сырого запроса (без SDK)
```python
import requests

s = requests.Session()
host = "https://panel.example.com:2053"

# 1) CSRF + login
csrf = s.get(f"{host}/csrf-token").json()["obj"]
r = s.post(f"{host}/login",
           json={"username": "admin", "password": "pass"},
           headers={"X-CSRF-Token": csrf})
assert r.json()["success"]

# 2) список инбаундов
data = s.get(f"{host}/panel/api/inbounds/list").json()
print(data["obj"])
```

---

## 7. Готовые рецепты для бота

### 7.1 Проверить статус подписки клиента
```python
import time

def get_client_status(api, email: str) -> dict | None:
    c = api.client.get_by_email(email)
    if c is None:
        return None
    now_ms = int(time.time() * 1000)
    days_left = (c.expiry_time - now_ms) / 86400000 if c.expiry_time > 0 else None
    used = c.up + c.down
    gb_left = (c.total_gb - used) / 1024**3 if c.total_gb > 0 else None
    return {
        "email": c.email,
        "enabled": c.enable,
        "expired": c.expiry_time != 0 and c.expiry_time < now_ms,
        "days_left": round(days_left, 1) if days_left is not None else "∞",
        "gb_used": round(used / 1024**3, 2),
        "gb_left": round(gb_left, 2) if gb_left is not None else "∞",
        "sub_link": f"{api.host}/sub/{c.sub_id}" if c.sub_id else None,
        "uuid": c.id,
    }
```

### 7.2 Продлить подписку (после оплаты)
```python
def extend_subscription(api, inbound_id: int, email: str, add_days: int):
    c = api.client.get_by_email(email)
    now_ms = int(time.time() * 1000)
    base = c.expiry_time if c.expiry_time > now_ms else now_ms  # продлеваем от max(сейчас, текущий срок)
    c.expiry_time = base + add_days * 86400000
    c.enable = True
    api.client.update(c.id, c)
```

### 7.3 Создать нового клиента (новая продажа)
```python
import uuid, time

def create_client(api, inbound_id: int, email: str, days: int, gb: int = 0,
                  limit_ip: int = 0, tg_id: int | None = None):
    cid = str(uuid.uuid4())
    client = Client(
        id=cid,
        email=email,
        enable=True,
        expiry_time=int((time.time() + days*86400)*1000) if days else 0,
        total_gb=gb * 1024**3,                 # 0 = безлимит
        limit_ip=limit_ip,
        sub_id=uuid.uuid4().hex[:16],
        tg_id=tg_id or "",
    )
    api.client.add(inbound_id, [client])
    return cid, client.sub_id
```

### 7.4 Заблокировать / разблокировать (неоплата / оплата)
```python
def set_enabled(api, email: str, enabled: bool):
    c = api.client.get_by_email(email)
    c.enable = enabled
    api.client.update(c.id, c)
```

### 7.5 Найти всех, у кого подписка скоро истекает (для напоминалок)
```python
def expiring_soon(api, within_days: int = 3) -> list[dict]:
    now_ms = int(time.time() * 1000)
    horizon = now_ms + within_days * 86400000
    result = []
    for ib in api.inbound.get_list():
        for c in (ib.client_stats or []):
            if c.expiry_time and now_ms < c.expiry_time <= horizon:
                result.append({"email": c.email, "expiry_ms": c.expiry_time})
    return result
```

### 7.6 Ссылка на подписку
Формат обычно: `https://<host>:<subPort>/<subPath>/<subId>`
(порт/путь подписки настраиваются в Settings → Subscription панели; по умолчанию часто `:2096/sub/`).
Бери `sub_id` из клиента и собирай ссылку под свою конфигурацию.

---

## 8. Хелперы / надёжность

### Авто-релогин при протухшей сессии
```python
from functools import wraps

def with_relogin(api):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            try:
                return fn(*a, **kw)
            except Exception:
                api.login()        # сессия протухла — логинимся заново
                return fn(*a, **kw)
        return wrapper
    return deco
```

Рекомендации:
- Для бота держи **один** объект `Api`/`AsyncApi` на всё приложение, логинься при старте.
- Периодически (раз в N минут) или по ошибке делай `login()` заново.
- Все ответы API содержат `success` — SDK сам кидает `ValueError`, если `success=false`.
- Сетевые ошибки SDK ретраит (`max_retries`, по умолчанию 3).
- Для самоподписанного TLS: `Api(..., use_tls_verify=False)`.

### Формат ответа API
```json
{ "success": true, "msg": "", "obj": { ... } }
```
`obj` — полезная нагрузка (клиент/список/статус). Если `success=false` — смотри `msg`.

---

## 9. Чеклист «что бот умеет делать с клиентом»

- [x] Узнать всё о клиенте — `get_by_email` (статус, срок, трафик, лимиты, uuid, sub)
- [x] Создать клиента (продажа) — `client.add`
- [x] Продлить срок — `update` (expiry_time)
- [x] Изменить лимит трафика — `update` (total_gb)
- [x] Изменить лимит устройств — `update` (limit_ip)
- [x] Включить/выключить (оплата/неоплата) — `update` (enable)
- [x] Сбросить трафик — `reset_stats`
- [x] Сбросить/посмотреть IP — `reset_ips` / `get_ips`
- [x] Удалить клиента — `client.delete`
- [x] Кто онлайн — `client.online`
- [x] Найти истекающих — обход `inbound.get_list()` → `client_stats`
- [x] Статус сервера — `server.get_status`

---

_Источник методов и сигнатур: исходники py3xui (api_client.py, api_inbound.py, api_server.py,
api_database.py, api_base.py, client.py, inbound.py) + Postman-документация 3x-ui. Перед продом
сверяй пути `/panel/api/...` со своей версией панели через встроенный Swagger (`API Docs`)._
