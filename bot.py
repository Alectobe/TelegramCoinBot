#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import asyncio
from datetime import datetime, time, timedelta

import psycopg2
import requests
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)

# ───── Настройка логирования ─────
logging.basicConfig(
    format='%(asctime)s — %(levelname)s — %(name)s — %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ───── Загрузка переменных окружения ─────
load_dotenv()
TG_TOKEN    = os.getenv('TG_TOKEN')
DB_HOST     = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT     = os.getenv('DB_PORT', '5432')
DB_NAME     = os.getenv('DB_NAME', 'bot_db')
DB_USER     = os.getenv('DB_USER', 'bot_user')
DB_PASS     = os.getenv('DB_PASS', 'password')
CMC_API_KEY = os.getenv('CMC_API_KEY', '348c6c58-7a4c-48dc-b4b0-4d6d790953ea')

# ───── Функция для подключения к PostgreSQL ─────
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

# ───── Таблица для логирования ошибок ─────
# CREATE TABLE IF NOT EXISTS error_logs (
#   id SERIAL PRIMARY KEY,
#   ts TIMESTAMPTZ DEFAULT NOW(),
#   function_name TEXT,
#   chat_id BIGINT NULL,
#   error_message TEXT
# );

def log_error_to_db(function_name: str, chat_id: int | None, error_message: str):
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO error_logs (function_name, chat_id, error_message)
            VALUES (%s, %s, %s)
            """,
            (function_name, chat_id, error_message)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Не удалось записать ошибку в БД: {e}")
    finally:
        if cur: cur.close()
        if conn: conn.close()

# ───── Словарь названий и форматирования ─────
SYMBOL_NAMES = {
    'USD':   ('Доллар', '$'),
    'EUR':   ('Евро', '$'),
    'RUB':   ('Рубль', '$'),
    'CNY':   ('Юань', '$'),
    'BTC':   ('BTC', '$'),
    'ETH':   ('ETH', '$'),
    'XAU':   ('Золото', '$'),
    'BRENT': ('Brent', '$'),
    'MOEX':  ('Мосбиржа', '$'),
    'RTS':   ('РТС', '$'),
    'RGBI':  ('RGBI', '$'),
}

# ───── Функция получения топ-20 криптовалют ─────
def get_top20_symbols() -> list[str]:
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': CMC_API_KEY
    }
    params = {'start': 1, 'limit': 20, 'convert': 'USD'}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status', {}).get('error_code') == 0 and data.get('data'):
            return [item['symbol'] for item in data['data']]
        else:
            logger.warning(f"Некорректный ответ CMC top-20: {data}")
            return []
    except Exception as e:
        err = f"get_top20_symbols: {e}"
        logger.error(err)
        log_error_to_db('get_top20_symbols', None, err)
        return []

# ───── Функция получения курса ─────
def get_exchange_rate(symbol: str, convert_to: str = 'USD') -> float:
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': CMC_API_KEY}
    fiat_list = ['USD', 'EUR', 'RUB', 'GBP', 'JPY', 'CNY']
    try:
        if symbol.upper() in fiat_list:
            url = 'https://pro-api.coinmarketcap.com/v1/tools/price-conversion'
            params = {'amount': 1, 'symbol': symbol.upper(), 'convert': convert_to.upper()}
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get('status', {}).get('error_code') == 0:
                return float(data['data']['quote'][convert_to.upper()]['price'])
            else:
                logger.warning(f"Некорректный ответ CMC price-conversion: {data}")
                return None
        else:
            url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'
            params = {'symbol': symbol.upper(), 'convert': convert_to.upper()}
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get('status', {}).get('error_code') == 0:
                return float(data['data'][symbol.upper()]['quote'][convert_to.upper()]['price'])
            else:
                logger.warning(f"Некорректный ответ CMC quotes/latest: {data}")
                return None
    except Exception as e:
        err = f"get_exchange_rate ({symbol}->{convert_to}): {e}"
        logger.error(err)
        log_error_to_db('get_exchange_rate', None, err)
        return None

# ───── Функция получения курса за вчера ─────
def get_yesterday_rate(symbol: str) -> float:
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT rate FROM currency_data
            WHERE symbol = %s
              AND ts <= (NOW() - INTERVAL '24 hours')
            ORDER BY ts DESC
            LIMIT 1
            """,
            (symbol.upper(),)
        )
        row = cur.fetchone()
        return float(row[0]) if row else None
    except Exception as e:
        err = f"get_yesterday_rate: {e}"
        logger.error(err)
        log_error_to_db('get_yesterday_rate', None, err)
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()

# ───── Функции работы с подписками и расписаниями ─────

def add_user(chat_id: int, chat_name: str):
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (chat_id, chat_name)
            VALUES (%s, %s)
            ON CONFLICT (chat_id) DO NOTHING
            """,
            (chat_id, chat_name)
        )
        conn.commit()
    except Exception as e:
        err = f"add_user: {e}"
        logger.error(err)
        log_error_to_db('add_user', chat_id, err)
    finally:
        if cur: cur.close()
        if conn: conn.close()

def add_subscription(chat_id: int, symbol: str) -> bool:
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO subscriptions (chat_id, symbol)
            VALUES (%s, %s)
            ON CONFLICT (chat_id, symbol) DO NOTHING
            """,
            (chat_id, symbol.upper())
        )
        changed = cur.rowcount
        conn.commit()
        return changed == 1
    except Exception as e:
        err = f"add_subscription: {e}"
        logger.error(err)
        log_error_to_db('add_subscription', chat_id, err)
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

def remove_subscription(chat_id: int, symbol: str) -> bool:
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM subscriptions
            WHERE chat_id = %s AND symbol = %s
            """,
            (chat_id, symbol.upper())
        )
        changed = cur.rowcount
        conn.commit()
        return changed == 1
    except Exception as e:
        err = f"remove_subscription: {e}"
        logger.error(err)
        log_error_to_db('remove_subscription', chat_id, err)
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

def clear_subscriptions(chat_id: int) -> int:
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM subscriptions
            WHERE chat_id = %s
            """,
            (chat_id,)
        )
        deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception as e:
        err = f"clear_subscriptions: {e}"
        logger.error(err)
        log_error_to_db('clear_subscriptions', chat_id, err)
        return 0
    finally:
        if cur: cur.close()
        if conn: conn.close()

def list_subscriptions(chat_id: int) -> list[str]:
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT symbol FROM subscriptions
            WHERE chat_id = %s
            ORDER BY symbol
            """,
            (chat_id,)
        )
        rows = cur.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        err = f"list_subscriptions: {e}"
        logger.error(err)
        log_error_to_db('list_subscriptions', chat_id, err)
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()

def upsert_schedule(chat_id: int, notify_time: str, enabled: bool):
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO schedules (chat_id, notify_time, enabled)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE
              SET notify_time = EXCLUDED.notify_time,
                  enabled = EXCLUDED.enabled
            """,
            (chat_id, notify_time, enabled)
        )
        conn.commit()
    except Exception as e:
        err = f"upsert_schedule: {e}"
        logger.error(err)
        log_error_to_db('upsert_schedule', chat_id, err)
    finally:
        if cur: cur.close()
        if conn: conn.close()

def get_schedule(chat_id: int) -> tuple[str | None, bool]:
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT notify_time, enabled FROM schedules
            WHERE chat_id = %s
            """,
            (chat_id,)
        )
        row = cur.fetchone()
        if row:
            time_obj = row[0]  # datetime.time
            return (time_obj.strftime("%H:%M"), row[1])
        else:
            return (None, False)
    except Exception as e:
        err = f"get_schedule: {e}"
        logger.error(err)
        log_error_to_db('get_schedule', chat_id, err)
        return (None, False)
    finally:
        if cur: cur.close()
        if conn: conn.close()

def upsert_interval(chat_id: int, interval_minutes: int | None, enabled: bool):
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if interval_minutes is None:
            cur.execute(
                """
                UPDATE intervals
                   SET enabled = %s
                 WHERE chat_id = %s
                """,
                (enabled, chat_id)
            )
        else:
            cur.execute(
                """
                INSERT INTO intervals (chat_id, interval_minutes, enabled)
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_id) DO UPDATE
                  SET interval_minutes = EXCLUDED.interval_minutes,
                      enabled = EXCLUDED.enabled
                """,
                (chat_id, interval_minutes, enabled)
            )
        conn.commit()
    except Exception as e:
        err = f"upsert_interval: {e}"
        logger.error(err)
        log_error_to_db('upsert_interval', chat_id, err)
    finally:
        if cur: cur.close()
        if conn: conn.close()

def get_interval(chat_id: int) -> tuple[int | None, bool]:
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT interval_minutes, enabled FROM intervals
            WHERE chat_id = %s
            """,
            (chat_id,)
        )
        row = cur.fetchone()
        if row:
            return (row[0], row[1])
        else:
            return (None, False)
    except Exception as e:
        err = f"get_interval: {e}"
        logger.error(err)
        log_error_to_db('get_interval', chat_id, err)
        return (None, False)
    finally:
        if cur: cur.close()
        if conn: conn.close()

# ───── Обработчики команд ─────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_name = (
        update.effective_chat.first_name
        or update.effective_chat.username
        or str(chat_id)
    )
    try:
        add_user(chat_id, chat_name)
        text = (
            f"Привет, {chat_name}! Я — бот для отслеживания курсов.\n\n"
            "Доступные команды:\n"
            "/subscribe <SYMBOL> — подписаться на курс (например, /subscribe BTC)\n"
            "/unsubscribe <SYMBOL> — отписаться от курса\n"
            "/unsubscribe_all — отписаться от всех сразу\n"
            "/subscribe_top20 — подписаться на топ-20 криптовалют сразу\n"
            "/list — показать текущие подписки\n"
            "/rates — показать текущие курсы ваших подписок в долларах\n"
            "/settime HH:MM — установить время ежедневных уведомлений\n"
            "/autoupdate on — включить автоуведомления\n"
            "/autoupdate off — выключить автоуведомления\n"
            "/setinterval <минуты> — установить периодические уведомления (каждые N минут)\n"
            "/clearinterval — выключить периодические уведомления\n\n"
            "Пример: /subscribe USD"
        )
        await update.message.reply_text(text)
    except Exception as e:
        err = f"start: {e}"
        logger.error(err)
        log_error_to_db('start', chat_id, err)

async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        if not context.args:
            await update.message.reply_text("Пожалуйста, укажите тикер: /subscribe USD или /subscribe BTC")
            return
        symbol = context.args[0].upper()
        success = add_subscription(chat_id, symbol)
        if success:
            await update.message.reply_text(f"Теперь подписан на {symbol} ✅")
        else:
            await update.message.reply_text(f"Не удалось подписаться (возможно, вы уже подписаны на {symbol})")
    except Exception as e:
        err = f"subscribe_cmd: {e}"
        logger.error(err)
        log_error_to_db('subscribe_cmd', chat_id, err)

async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        if not context.args:
            await update.message.reply_text("Укажите тикер для отписки: /unsubscribe BTC")
            return
        symbol = context.args[0].upper()
        success = remove_subscription(chat_id, symbol)
        if success:
            await update.message.reply_text(f"Отписались от {symbol} ✅")
        else:
            await update.message.reply_text(f"Вы не были подписаны на {symbol}")
    except Exception as e:
        err = f"unsubscribe_cmd: {e}"
        logger.error(err)
        log_error_to_db('unsubscribe_cmd', chat_id, err)

async def unsubscribe_all_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        deleted = clear_subscriptions(chat_id)
        if deleted > 0:
            await update.message.reply_text(f"Вы отписались от всех {deleted} подписок ✅")
        else:
            await update.message.reply_text("У вас не было подписок для удаления.")
    except Exception as e:
        err = f"unsubscribe_all_cmd: {e}"
        logger.error(err)
        log_error_to_db('unsubscribe_all_cmd', chat_id, err)

async def subscribe_top20_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        symbols = get_top20_symbols()
        if not symbols:
            await update.message.reply_text("Не удалось получить топ-20. Попробуйте позже.")
            return
        added, already = [], []
        for sym in symbols:
            if add_subscription(chat_id, sym):
                added.append(sym)
            else:
                already.append(sym)
        parts = []
        if added:
            parts.append("Подписаны на топ-20:\n" + ", ".join(added))
        if already:
            parts.append("Уже были подписки:\n" + ", ".join(already))
        await update.message.reply_text("\n\n".join(parts))
    except Exception as e:
        err = f"subscribe_top20_cmd: {e}"
        logger.error(err)
        log_error_to_db('subscribe_top20_cmd', chat_id, err)

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        subs = list_subscriptions(chat_id)
        if subs:
            await update.message.reply_text("Ваши подписки:\n" + "\n".join(subs))
        else:
            await update.message.reply_text("У вас пока нет подписок. Используйте /subscribe <SYMBOL>")
    except Exception as e:
        err = f"list_cmd: {e}"
        logger.error(err)
        log_error_to_db('list_cmd', chat_id, err)

async def rates_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        subs = list_subscriptions(chat_id)
        if not subs:
            await update.message.reply_text("Вы ещё ни на одну валюту не подписаны. Используйте /subscribe <SYMBOL>.")
            return
        lines = []
        now = datetime.now()
        for sym in subs:
            current = get_exchange_rate(sym, 'USD')
            yesterday = get_yesterday_rate(sym)
            name, sign = SYMBOL_NAMES.get(sym, (sym, '$'))
            if current is None:
                lines.append(f"❓{name} — нет текущих данных")
                continue
            if yesterday not in (None, 0):
                pct = (current - yesterday)/yesterday*100.0
                arrow = "🟢" if pct > 0 else ("🔻" if pct < 0 else "⏺")
                pct_str = f"{'+' if pct>0 else ''}{pct:.2f}%"
            else:
                arrow, pct_str = "⏺", "0.00%"
            price_str = f"{sign}{current:,.2f}".replace(",", " ")
            lines.append(f"{arrow}{name} {pct_str}  {price_str}")
        text = "Курсы на " + now.strftime("%Y-%m-%d %H:%M") + ":\n" + "\n".join(lines)
        await update.message.reply_text(text)
    except Exception as e:
        err = f"rates_cmd: {e}"
        logger.error(err)
        log_error_to_db('rates_cmd', chat_id, err)

async def settime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        if not context.args:
            await update.message.reply_text("Укажите время в формате HH:MM (например, /settime 15:30).")
            return
        t = context.args[0]
        hh, mm = map(int, t.split(":"))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
        upsert_schedule(chat_id, t, False)
        await update.message.reply_text(f"Время ежедневных уведомлений установлено на {t}. Чтобы включить, используйте /autoupdate on")
    except Exception as e:
        err = f"settime_cmd: {e}"
        logger.error(err)
        log_error_to_db('settime_cmd', chat_id, err)
        await update.message.reply_text("Неверный формат времени. Используйте HH:MM в 24-часовом формате.")

async def autoupdate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        if not context.args:
            await update.message.reply_text("Укажите on или off: /autoupdate on")
            return
        mode = context.args[0].lower()
        notify_time_str, _ = get_schedule(chat_id)
        if not notify_time_str:
            await update.message.reply_text("Сначала установите время через /settime HH:MM")
            return
        hh, mm = map(int, notify_time_str.split(":"))
        notify_time_obj = time(hour=hh, minute=mm)
        if mode == "on":
            upsert_schedule(chat_id, notify_time_str, True)
            await update.message.reply_text(f"Ежедневные уведомления включены. Каждый день в {notify_time_str} я пришлю курсы.")
            if context.job_queue:
                context.job_queue.run_daily(
                    send_rates,
                    notify_time_obj,
                    chat_id=chat_id,
                    name=f"daily_{chat_id}"
                )
            else:
                logger.error("JobQueue недоступен. Убедитесь, что установлен python-telegram-bot версии ≥ 22.")
        elif mode == "off":
            upsert_schedule(chat_id, notify_time_str, False)
            await update.message.reply_text("Ежедневные уведомления выключены.")
            if context.job_queue:
                jobs = context.job_queue.get_jobs_by_name(f"daily_{chat_id}")
                for job in jobs:
                    job.schedule_removal()
            else:
                logger.error("JobQueue недоступен. Убедитесь, что установлен python-telegram-bot версии ≥ 22.")
        else:
            await update.message.reply_text("Неверный параметр. Используйте /autoupdate on или /autoupdate off")
    except Exception as e:
        err = f"autoupdate_cmd: {e}"
        logger.error(err)
        log_error_to_db('autoupdate_cmd', chat_id, err)

async def setinterval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        if not context.args:
            await update.message.reply_text("Укажите интервал в минутах: /setinterval 60")
            return
        minutes = int(context.args[0])
        if minutes <= 0:
            raise ValueError
        upsert_interval(chat_id, minutes, True)
        await update.message.reply_text(f"Периодические уведомления включены: каждые {minutes} минут.")
        if context.job_queue:
            jobs = context.job_queue.get_jobs_by_name(f"interval_{chat_id}")
            for job in jobs:
                job.schedule_removal()
            context.job_queue.run_repeating(
                send_rates,
                interval=timedelta(minutes=minutes),
                first=0,
                chat_id=chat_id,
                name=f"interval_{chat_id}"
            )
        else:
            logger.error("JobQueue недоступен. Убедитесь, что установлен python-telegram-bot версии ≥ 22.")
    except Exception as e:
        err = f"setinterval_cmd: {e}"
        logger.error(err)
        log_error_to_db('setinterval_cmd', chat_id, err)
        await update.message.reply_text("Неверный интервал. Введите целое положительное число минут.")

async def clearinterval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        _, enabled = get_interval(chat_id)
        if not enabled:
            await update.message.reply_text("Периодические уведомления уже выключены.")
            return
        upsert_interval(chat_id, None, False)
        await update.message.reply_text("Периодические уведомления выключены.")
        if context.job_queue:
            jobs = context.job_queue.get_jobs_by_name(f"interval_{chat_id}")
            for job in jobs:
                job.schedule_removal()
        else:
            logger.error("JobQueue недоступен. Убедитесь, что установлен python-telegram-bот версии ≥ 22.")
    except Exception as e:
        err = f"clearinterval_cmd: {e}"
        logger.error(err)
        log_error_to_db('clearinterval_cmd', chat_id, err)

# ───── Функция отправки курсов ─────

async def send_rates(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        name_parts = job.name.split("_")
        chat_id = int(name_parts[-1])
        subs = list_subscriptions(chat_id)
        if not subs:
            upsert_schedule(chat_id, get_schedule(chat_id)[0], False)
            upsert_interval(chat_id, None, False)
            job.schedule_removal()
            return

        lines = []
        now = datetime.now()
        for sym in subs:
            current = get_exchange_rate(sym, 'USD')
            yesterday = get_yesterday_rate(sym)
            name, sign = SYMBOL_NAMES.get(sym, (sym, '$'))
            if current is None:
                lines.append(f"❓{name} — нет текущих данных")
                continue
            if yesterday not in (None, 0):
                pct = (current - yesterday)/yesterday*100.0
                arrow = "🟢" if pct > 0 else ("🔻" if pct < 0 else "⏺")
                pct_str = f"{'+' if pct>0 else ''}{pct:.2f}%"
            else:
                arrow, pct_str = "⏺", "0.00%"
            price_str = f"{sign}{current:,.2f}".replace(",", " ")
            lines.append(f"{arrow}{name} {pct_str}  {price_str}")

        header = "Курсы на " + now.strftime("%Y-%m-%d %H:%M")
        text = header + ":\n" + "\n".join(lines)
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        try:
            chat_id = int(job.name.split("_")[-1])
        except:
            chat_id = None
        err = f"send_rates: {e}"
        logger.error(err)
        log_error_to_db('send_rates', chat_id, err)

# ───── Функция on_startup ─────

async def on_startup(application):
    conn, cur = None, None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Восстанавливаем ежедневные уведомления
        cur.execute("SELECT chat_id, notify_time FROM schedules WHERE enabled = TRUE")
        rows = cur.fetchall()
        for (chat_id, notify_time_obj) in rows:
            if application.job_queue:
                application.job_queue.run_daily(
                    send_rates,
                    notify_time_obj,
                    chat_id=chat_id,
                    name=f"daily_{chat_id}"
                )
            else:
                logger.error("JobQueue недоступен при старте ежедневных. Установите python-telegram-bot ≥ 22.")

        # Восстанавливаем периодические уведомления
        cur.execute("SELECT chat_id, interval_minutes FROM intervals WHERE enabled = TRUE")
        rows_i = cur.fetchall()
        for (chat_id, interval_minutes) in rows_i:
            if application.job_queue:
                application.job_queue.run_repeating(
                    send_rates,
                    interval=timedelta(minutes=interval_minutes),
                    first=0,
                    chat_id=chat_id,
                    name=f"interval_{chat_id}"
                )
            else:
                logger.error("JobQueue недоступен при старте интервалов. Установите python-telegram-bot ≥ 22.")

        logger.info("Загружены существующие задачи уведомлений.")
    except Exception as e:
        err = f"on_startup: {e}"
        logger.error(err)
        log_error_to_db('on_startup', None, err)
    finally:
        if cur: cur.close()
        if conn: conn.close()

# ───── Основная функция ─────

def main():
    app = ApplicationBuilder().token(TG_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscribe_cmd))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_cmd))
    app.add_handler(CommandHandler("unsubscribe_all", unsubscribe_all_cmd))
    app.add_handler(CommandHandler("subscribe_top20", subscribe_top20_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("rates", rates_cmd))
    app.add_handler(CommandHandler("settime", settime_cmd))
    app.add_handler(CommandHandler("autoupdate", autoupdate_cmd))
    app.add_handler(CommandHandler("setinterval", setinterval_cmd))
    app.add_handler(CommandHandler("clearinterval", clearinterval_cmd))

    try:
        asyncio.get_event_loop().run_until_complete(on_startup(app))
    except RuntimeError:
        asyncio.run(on_startup(app))

    logger.info("Запускаем бота...")
    app.run_polling()

if __name__ == '__main__':
    main()
