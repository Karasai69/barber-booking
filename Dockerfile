# Один образ для всех Python-сервисов: api, bot, worker, beat, migrate.
# Чем запускать, решает command в docker-compose.yml.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Сначала только зависимости: пока requirements.txt не менялся,
# Docker берёт этот слой из кэша и не переустанавливает пакеты при каждой сборке.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Не запускаем приложение от root.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
