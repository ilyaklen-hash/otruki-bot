#!/usr/bin/env python3
"""
ОТ РУКИ — Telegram-бот для записи на занятия
==============================================

Установка:
    pip install "python-telegram-bot[socks]" gspread google-auth

Запуск:
    python bot.py

Что делает бот:
    1. Встречает нового пользователя
    2. Показывает ближайшие занятия
    3. Принимает запись: имя → контакт
    4. Отправляет подтверждение клиенту + реквизиты оплаты
    5. Уведомляет администратора о новой записи
    6. Записывает бронирование в Google Sheets
"""

import logging
import os
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes,
)

# Google Sheets (опционально — работает если настроен GOOGLE_CREDENTIALS)
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# ═══════════════════════════════════════════════════════════
#  НАСТРОЙКИ — заполнить перед запуском
# ═══════════════════════════════════════════════════════════

BOT_TOKEN = "8771338517:AAEs0mfa_cPoWKySsFXLkWQb3DNKjO8c4Z0"

ADMIN_ID = 163103731  # @klenklen

# ── Реквизиты оплаты ──────────────────────────────────────────────────────────
PAYMENT_PHONE  = "+7 926 115 3033"
PAYMENT_NAME   = "Михаил Г."
PAYMENT_BANK   = "Т-Банк"

# ── Google Sheets (необязательно) ─────────────────────────────────────────────
# Переменная окружения GOOGLE_CREDENTIALS — JSON-ключ сервисного аккаунта.
# Переменная GOOGLE_SHEET_ID — ID таблицы (из URL: .../spreadsheets/d/<ID>/...).
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# ═══════════════════════════════════════════════════════════
#  РАСПИСАНИЕ ЗАНЯТИЙ
#  Обновляйте этот список перед каждым набором
# ═══════════════════════════════════════════════════════════

SESSIONS = [
    # ── Свободное рисование (Женя Бородина) · 5 000 ₽ · Вт/Чт ──────────────
    {
        "id":      "s1",
        "date":    "17 марта, вторник",
        "time":    "19:00",
        "type":    "Свободное рисование",
        "teacher": "Женя Бородина",
        "price":   "5 000 ₽",
        "spots":   10,
    },
    {
        "id":      "s2",
        "date":    "19 марта, четверг",
        "time":    "19:00",
        "type":    "Свободное рисование",
        "teacher": "Женя Бородина",
        "price":   "5 000 ₽",
        "spots":   10,
    },
    {
        "id":      "s3",
        "date":    "24 марта, вторник",
        "time":    "19:00",
        "type":    "Свободное рисование",
        "teacher": "Женя Бородина",
        "price":   "5 000 ₽",
        "spots":   10,
    },
    {
        "id":      "s4",
        "date":    "26 марта, четверг",
        "time":    "19:00",
        "type":    "Свободное рисование",
        "teacher": "Женя Бородина",
        "price":   "5 000 ₽",
        "spots":   10,
    },
    # ── Основы с нуля (Полина Ярцева) · 6 000 ₽ / 20 000 ₽ курс · Пн/Ср ───
    {
        "id":      "s5",
        "date":    "24 марта, понедельник",
        "time":    "19:00",
        "type":    "Основы с нуля",
        "teacher": "Полина Ярцева",
        "price":   "6 000 ₽ (или 20 000 ₽ за курс ×4)",
        "spots":   10,
    },
    {
        "id":      "s6",
        "date":    "25 марта, среда",
        "time":    "19:00",
        "type":    "Основы с нуля",
        "teacher": "Полина Ярцева",
        "price":   "6 000 ₽ (или 20 000 ₽ за курс ×4)",
        "spots":   10,
    },
]

# ═══════════════════════════════════════════════════════════
#  КОД БОТА — менять не нужно
# ═══════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# ── Google Sheets helper ───────────────────────────────────────────────────────
def _append_to_sheet(row: list) -> None:
    """Добавляет строку в Google Sheets. Тихо падает, если не настроено."""
    if not GSPREAD_AVAILABLE or not GOOGLE_SHEET_ID:
        return
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if not creds_json:
        return
    try:
        creds_data = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.sheet1
        # Создать заголовки если таблица пустая
        if ws.row_count == 0 or not ws.row_values(1):
            ws.append_row(["Дата записи", "Имя", "Контакт", "Telegram", "Занятие", "Преподаватель", "Дата занятия", "Цена"])
        ws.append_row(row)
    except Exception as e:
        log.warning("Не удалось записать в Google Sheets: %s", e)

# Состояния диалога
CHOOSE_SESSION, GET_NAME, GET_PHONE = range(3)


# ── /start ────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[
        InlineKeyboardButton("📅 Посмотреть занятия", callback_data="show_sessions"),
    ]]
    await update.message.reply_text(
        "Привет! Это *ОТ РУКИ* — школа рисования для взрослых 🎨\n\n"
        "Занятия в мастерской художника Миши. 2,5 часа, группа 8–12 человек, "
        "все материалы включены. Старт *17 марта*.\n\n"
        "Два направления:\n"
        "• *Свободное рисование* (Женя Бородина) — Вт/Чт · *5 000 ₽*\n"
        "• *Основы с нуля* (Полина Ярцева) — Пн/Ср · *6 000 ₽* разово или *20 000 ₽* курс ×4",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSE_SESSION


# ── Список занятий ────────────────────────────────────────
async def show_sessions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    available = [s for s in SESSIONS if s["spots"] > 0]

    if not available:
        await query.edit_message_text(
            "Сейчас все места заняты 😔\n\n"
            "Напишите нам — мы добавим вас в лист ожидания: @otrookibot"
        )
        return ConversationHandler.END

    keyboard = []
    for s in available:
        spots_txt = f"{s['spots']} {_spots_word(s['spots'])}"
        label = f"{s['date']} · {s['type']} · {spots_txt}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"ses:{s['id']}")])

    await query.edit_message_text(
        "Выберите дату:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSE_SESSION


# ── Выбрали дату ──────────────────────────────────────────
async def session_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    session_id = query.data.split(":", 1)[1]
    session = next((s for s in SESSIONS if s["id"] == session_id), None)

    if not session or session["spots"] <= 0:
        await query.edit_message_text("Это место уже занято. Попробуйте /start — покажу другие даты.")
        return ConversationHandler.END

    ctx.user_data["session"] = session

    await query.edit_message_text(
        f"Отлично! Вы выбрали:\n\n"
        f"📅 *{session['date']}* в {session['time']}\n"
        f"🎨 *{session['type']}* · {session['teacher']}\n"
        f"💳 {session['price']}\n\n"
        f"Как вас зовут?",
        parse_mode="Markdown",
    )
    return GET_NAME


# ── Имя ───────────────────────────────────────────────────
async def get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Напишите, пожалуйста, ваше имя:")
        return GET_NAME

    ctx.user_data["name"] = name
    await update.message.reply_text(
        f"Приятно, {name}!\n\n"
        "Оставьте ваш номер телефона или @username в Telegram — "
        "мы пришлём адрес и напомним накануне:"
    )
    return GET_PHONE


# ── Контакт + финал ───────────────────────────────────────
async def get_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.text.strip()
    session  = ctx.user_data.get("session", {})
    name     = ctx.user_data.get("name", "—")
    user     = update.effective_user

    # Уменьшить количество мест
    for s in SESSIONS:
        if s["id"] == session.get("id"):
            s["spots"] = max(0, s["spots"] - 1)
            break

    # Подтверждение клиенту
    await update.message.reply_text(
        f"✅ Готово! Вы записаны.\n\n"
        f"📅 *{session.get('date')}* в {session.get('time')}\n"
        f"🎨 {session.get('type')} · {session.get('teacher')}\n"
        f"💳 {session.get('price')}\n\n"
        f"💸 *Оплата* — переведите на {PAYMENT_BANK} по номеру "
        f"`{PAYMENT_PHONE}` ({PAYMENT_NAME})\n\n"
        f"Накануне пришлём адрес и все детали. "
        f"Если что-то изменится — напишите сюда, мы поймём 🙂\n\n"
        f"До встречи ✦",
        parse_mode="Markdown",
    )

    # Уведомление администратору
    tg_ref = f"@{user.username}" if user.username else f"[{user.first_name}](tg://user?id={user.id})"
    admin_msg = (
        f"🆕 *Новая запись!*\n\n"
        f"👤 {name}\n"
        f"📞 {contact}\n"
        f"🔗 {tg_ref}\n\n"
        f"📅 {session.get('date')} · {session.get('time')}\n"
        f"🎨 {session.get('type')} · {session.get('teacher')}\n"
        f"💳 {session.get('price')}"
    )
    try:
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
    except Exception as e:
        log.warning("Не удалось отправить уведомление администратору: %s", e)

    # Запись в Google Sheets
    _append_to_sheet([
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        name,
        contact,
        tg_ref,
        session.get("type", ""),
        session.get("teacher", ""),
        f"{session.get('date')} {session.get('time')}",
        session.get("price", ""),
    ])

    return ConversationHandler.END


# ── /cancel ───────────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Хорошо! Когда решите записаться — напишите /start 🙂"
    )
    return ConversationHandler.END


# ── Хелпер ────────────────────────────────────────────────
def _spots_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "место"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "места"
    return "мест"


# ═══════════════════════════════════════════════════════════
#  ЗАПУСК
# ═══════════════════════════════════════════════════════════

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_SESSION: [
                CallbackQueryHandler(show_sessions,  pattern=r"^show_sessions$"),
                CallbackQueryHandler(session_chosen, pattern=r"^ses:"),
            ],
            GET_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GET_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)

    log.info("Бот ОТ РУКИ запущен ✦")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
