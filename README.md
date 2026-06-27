# 3x-ui Telegram бот (триал → напоминания → оплата)

Telegram-бот поверх панели **3x-ui** (через `py3xui`): выдаёт пробный VPN-ключ,
ведёт сценарий отложенных уведомлений, принимает оплату по PDF-чеку и продлевает
подписку. Реализация по [BOT_PLAN.md](BOT_PLAN.md); API-справочник —
[3X-UI_API_CHEATSHEET.md](3X-UI_API_CHEATSHEET.md).

## Что умеет

- `/start` → приветствие + кнопка «Попробовать».
- «Попробовать» → создаёт клиента в 3x-ui (email `@username` или `temp-<id>`,
  срок 1 день, 2 устройства, безлимит трафика, на всех инбаундах) и отдаёт ссылку подписки.
- Через 4 ч проверяет трафик: был → оффер оплаты; не был → за 3 ч до конца просит протестировать.
- «Оплатить» с гейтом по username: нет username → инструкция → «Username установлен»
  → смена email клиента в 3x-ui → только потом ссылка на оплату.
- Приём PDF-чека → проверка суммы (200 ₽) + анти-дубль → продление на месяц →
  уведомление за 1 день до конца.
- `/panel` (`/admin`) для админов → WebApp-кнопка с родным UI 3x-ui.

## Структура

```
bot/
  config.py            # конфиг из .env
  db.py                # SQLite: бизнес-состояние воронки + анти-дубль чеков
  xui.py               # обёртка над py3xui (триал, смена email, продление)
  receipt.py           # парсинг PDF-чека (pdfplumber)
  scheduler.py         # APScheduler: +4ч / -3ч / -1день
  texts.py             # тексты сообщений
  keyboards.py         # inline-клавиатуры
  handlers/
    start.py           # /start
    trial.py           # «Попробовать»
    payment.py         # «Оплатить» + username-гейт
    receipt_handler.py # приём PDF-чека
    admin.py           # /panel (WebApp)
  main.py              # точка входа
```

## Запуск

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt

copy .env.example .env          # затем заполни значения
python -m bot.main
```

## Конфигурация (.env)

См. [.env.example](.env.example). Ключевое:
- `BOT_TOKEN`, `ADMIN_IDS` — Telegram.
- `XUI_HOST` / `XUI_USERNAME` / `XUI_PASSWORD` (или `XUI_TOKEN`) — доступ к панели.
  `XUI_HOST` — без хвоста `/panel` (см. шпаргалку §1).
- `SUB_BASE` — база ссылки подписки (`{SUB_BASE}/{sub_id}`), из Settings → Subscription.
- `XUI_PANEL_URL` — https-URL панели для админской WebApp-кнопки.
- `PAYMENT_URL`, `PRICE_RUB` — оплата.
- Тайминги (`TRIAL_DAYS`, `CHECK_TRAFFIC_AFTER_HOURS`, ...) — для теста можно уменьшить.

## Что проверить перед продом (из BOT_PLAN.md §9)

1. **Смена email через `update`** — работает ли на твоей версии панели; если нет —
   в `xui.change_email` есть фолбэк «пересоздать + удалить» (проверь его).
2. **Формат ссылки подписки** (`SUB_BASE`) — порт/путь из Settings → Subscription.
3. **Валидация чека** (`bot/receipt.py`) — подстрой `SUCCESS_MARKERS` и поиск суммы
   под формат чеков своего банка; при сканах без текстового слоя нужен OCR.
4. **Один `sub_id` на все инбаунды** — убедись, что подписка отдаёт все ключи.

## Заметки

- Jobstore планировщика — in-memory; при старте `rehydrate()` восстанавливает джобы из БД.
  Для строгой надёжности можно подключить персистентный jobstore APScheduler (SQLAlchemy).
- Один объект `XUI`/`AsyncApi` на всё приложение + авто-релогин при протухшей сессии.
