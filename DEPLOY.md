# Деплой бота на сервер (Docker Compose) + code-server

Инструкция для финского VPS (Ubuntu/Debian). Терминал нужен только при первой
настройке — дальше всё можно делать через code-server (VS Code в браузере).

> Почему сервер, а не локально: на сервере в Финляндии Telegram API доступен
> стабильно — пропадут обрывы соединения, которые были при запуске с домашнего ПК.

---

## Часть 1. Запуск бота (Docker) — обязательно

### 1. Зайти на сервер
Через SSH (или веб-консоль у провайдера). Один раз, для установки.
```bash
ssh root@ТВОЙ_IP_СЕРВЕРА
```

### 2. Установить Docker (одна команда)
```bash
curl -fsSL https://get.docker.com | sh
```

### 3. Скачать проект с GitHub
```bash
cd /opt
git clone https://github.com/Nullr108/3x-ui-bot_.git bot
cd bot
```
> Если репозиторий приватный — git попросит логин/токен. Проще всего сделать репо
> публичным (секретов в нём нет, они только в `.env`), либо клонировать с
> Personal Access Token: `https://<ТОКЕН>@github.com/Nullr108/3x-ui-bot_.git`.

### 4. Создать и заполнить `.env`
```bash
cp .env.example .env
nano .env        # отредактировать значения, затем Ctrl+O, Enter, Ctrl+X
```
Обязательно заполнить:
- `BOT_TOKEN`, `ADMIN_IDS`
- `XUI_HOST`, `XUI_USERNAME`, `XUI_PASSWORD` (или `XUI_TOKEN`)
- `XUI_PANEL_URL` (https), `SUB_BASE`
- `PAYMENT_URL`, `PROMO_CODE`, `FRIENDS_CODE`

> `DB_PATH` трогать не нужно — в Docker база автоматически кладётся в постоянный
> volume (`/data/bot.db`) и переживает обновления/пересборку.

### 5. Запустить
```bash
docker compose up -d --build
```
Бот собрался и работает в фоне. Он сам перезапустится после падения и после
перезагрузки сервера.

### 6. Проверить, что живой
```bash
docker compose logs -f
```
Ждём строки `Telegram доступен: @...` и `Start polling`. Выход из логов — Ctrl+C
(бот при этом продолжает работать). В Telegram отправь боту `/selftest` (как админ)
— должно быть 11/11.

---

## Управление (шпаргалка)

| Действие | Команда (в папке `/opt/bot`) |
|----------|------------------------------|
| Логи в реальном времени | `docker compose logs -f` |
| Перезапустить | `docker compose restart` |
| Остановить | `docker compose down` |
| Запустить снова | `docker compose up -d` |
| Обновить из GitHub | `git pull && docker compose up -d --build` |
| Статус | `docker compose ps` |

После правки `.env` нужно применить: `docker compose up -d` (пересоздаст контейнер
с новыми значениями).

---

## Часть 2. code-server (VS Code в браузере) — по желанию

Чтобы править файлы и нажимать команды без «рытья в терминале».

### Установка
```bash
curl -fsSL https://code-server.dev/install.sh | sh
sudo systemctl enable --now code-server@$USER
```

### Задать пароль и открыть доступ
```bash
nano ~/.config/code-server/config.yaml
```
Привести к виду (пароль придумай СВОЙ, длинный):
```yaml
bind-addr: 0.0.0.0:8080
auth: password
password: ПРИДУМАЙ_ДЛИННЫЙ_ПАРОЛЬ
cert: false
```
Применить:
```bash
sudo systemctl restart code-server@$USER
```
Открыть в браузере: `http://ТВОЙ_IP_СЕРВЕРА:8080` → ввести пароль →
File ▸ Open Folder ▸ `/opt/bot`.

Теперь `.env` правишь прямо в браузере, а команды (`docker compose ...`) выполняешь
во встроенном терминале code-server (меню ▸ Terminal ▸ New Terminal) — это тот же
терминал, но в окне браузера.

### ⚠️ Безопасность code-server
- Пароль — **длинный и уникальный** (это полный доступ к серверу!).
- Лучше закрыть порт 8080 фаерволом для всех, кроме своего IP, или ходить через
  SSH-туннель. Идеально — повесить за HTTPS (домен + Caddy/Nginx). Без шифрования
  пароль ходит по сети открыто — для постоянной работы небезопасно.
- Если code-server нужен только изредка — включай его на время и выключай:
  `sudo systemctl stop code-server@$USER`.

---

## Частые вопросы

- **Бот не стартует / нет «Telegram доступен»** → `docker compose logs -f`, смотри
  ошибку. Чаще всего — опечатка в `.env`.
- **Сменил `.env`** → `docker compose up -d` (или `restart`).
- **Обновил код на GitHub** → на сервере `git pull && docker compose up -d --build`.
- **База/пользователи** лежат в volume `botdata` и не теряются при пересборке.
  Сбросить начисто: `docker compose down -v` (удалит и базу!).
