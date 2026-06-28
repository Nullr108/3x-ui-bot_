# Образ бота: Python 3.12 (стабильный, под него есть готовые wheel'ы всех зависимостей)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Сначала зависимости (кэшируется, пока requirements.txt не менялся)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код бота (.env НЕ копируем — он подаётся через env_file во время запуска)
COPY bot ./bot

CMD ["python", "-m", "bot.main"]
