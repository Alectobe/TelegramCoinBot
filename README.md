# Telegram-бот для мониторинга курсов валют с использованием Yandex Cloud

## 📌 Описание проекта

Данный проект представляет собой Telegram-бота, реализованного с использованием облачной инфраструктуры **Yandex Cloud**. Бот предназначен для мониторинга курсов валют и криптовалют, хранения данных в облачной базе PostgreSQL и визуализации аналитики в **Yandex DataLens**.

## 🧾 Содержимое репозитория

- `bot.py` — основной скрипт, реализующий логику взаимодействия Telegram-бота с пользователем, работу с API и базой данных.
- `db_schema.sql` — SQL-скрипты для создания таблиц PostgreSQL.
- `.env.template` — шаблон конфигурационного файла для переменных окружения (токены, ключи, параметры подключения)

## 📊 Визуализация

Визуализация выполняется в Yandex DataLens с привязкой к облачной БД. Построены следующие панели:
- Актуальные курсы валют;
- Историческая динамика по дням;
- Частота использования команд;
- Статистика ошибок и отклонений;
- Статистика подписок по пользователям.

## 🔗 Демо

Telegram-бот: @CoinMarketCaperbot Ссылка: https://t.me/@CoinMarketCaperbot
DataLens Dashboard: 
<img width="1406" alt="image" src="https://github.com/user-attachments/assets/2d437619-0cc4-4d6d-ae6c-be327f62a02d" />


## ⚙️ Требования

- Python 3.10+
- PostgreSQL (Managed in Yandex.Cloud)
- Yandex Cloud аккаунт
- CoinMarketCap API ключ
- Библиотеки: `python-telegram-bot`, `apscheduler`, `sqlalchemy`, `httpx`, `dotenv`, `psycopg2`

