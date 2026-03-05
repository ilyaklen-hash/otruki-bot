#!/usr/bin/env python3
"""
ОТ РУКИ — Telegram-бот для записи на занятия
==============================================

Установка:
    pip install "python-telegram-bot[socks]" gspread google-auth

Запуск:
    python bot.py

Что делает бот:
    1. Предлагает два продукта: курс или свободное рисование
    2. Записывает на выбранное занятие — нужно только имя
    3. Автоматически захватывает Telegram username для CRM
    4. Отправляет адрес и реквизиты оплаты
    5. Уведомляет администратора
    6. Записывает в Google Sheets (если настроено)
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

# Google Sheets (опционально)
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# ═══════════════════════════════════════════════════════════
#  НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════

BOT_TOKEN = "8771338517:AAEs0mfa_cPoWKySsFXLkWQb3DNKjO8c4Z0"
ADMIN_ID  = 163103731  # @klenklen

# ── Адрес ─────────────────────────────────────────────────────────────────────
ADDRESS = (
    "📍 Большой Сергиевский переулок, 11\n"
    "Домофон: 9300, код вызова 12\n"
    "5 этаж, кв. 12"
)

# ── Реквизиты оплаты ──────────────────────────────────────────────────────────
PAYMENT_PHONE = "+7 926 115 3033"
PAYMENT_NAME  = "Михаил Г."
PAYMENT_BANK  = "Т-Банк"

# ── Google Sheets ──────────────────────────────────────────────────────────────
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# ═══════════════════════════════════════════════════════════
#  ПРОДУКТЫ
#  Обновляйте перед каждым набором
# ═══════════════════════════════════════════════════════════

# Курс «Основы рисования» — 4 занятия, 20 000 ₽
COURSE = {
    "id":      "course",
    "name":    "Курс «Основы рисования»",
    "teacher": "Полина Ярцева",
    "schedule":"Пн/Ср · 19:00 · старт 25 марта",
    "lessons": "4 занятия",
    "price":   "20 000 ₽",
    "spots":   10,
}

# Свободное рисование — разовые занятия, 5 000 ₽
# Обновляйте список: записывайте только предстоящую неделю
FREE_SESSIONS = [
    {"id": "s1", "date": "17 марта, вторник",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "s2", "date": "19 марта, четверг",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "s3", "date": "24 марта, вторник",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "s4", "date": "26 марта, четверг",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
]

# ═══════════════════════════════════════════════════════════
#  КОД БОТА
# ═══════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# Состояния диалога
CHOOSE_PRODUCT, CHOOSE_SESSION, GET_NAME = range(3)


# ── Google Sheets helper ───────────────────────────────────
def _append_to_sheet(row: list) -> None:
    if not GSPREAD_AVAILABLE or not GOOGLE_SHEET_ID:
        return
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if not creds_json:
        return
    try:
        creds_data = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds  = Credentials.from_service_account_info(creds_data, scopes=scopes)
        gc     = gspread.authorize(creds)
        ws     = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        if not ws.row_values(1):
            ws.append_row(["Дата записи", "Имя", "Telegram", "Занятие", "Преподаватель", "Дата занятия", "Цена"])
        ws.append_row(row)
    except Exception as e:
        log.warning("Google Sheets: %s", e)


# ── /start ─────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("🎨 Свободное рисование  · 5 000 ₽", callback_data="product:free")],
        [InlineKeyboardButton("📚 Курс «Основы рисования»  · 20 000 ₽", callback_data="product:course")],
    ]
    await update.message.reply_text(
        "Привет! Это *ОТ РУКИ* — школа графики в Москве 🎨\n\n"
        "Рисуем в мастерской художника Миши, небольшими группами. "
        "Все материалы включены, нужно только желание.\n\n"
        "Есть два формата — выбирай что ближе:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSE_PRODUCT


# ── Выбор продукта ─────────────────────────────────────────
async def choose_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    product = query.data.split(":", 1)[1]

    if product == "course":
        # Показываем курс — одна кнопка «Записаться»
        if COURSE["spots"] <= 0:
            await query.edit_message_text(
                "На курс все места уже заняты 😔\n\n"
                "Напишите нам — добавим в лист ожидания: @otrookibot"
            )
            return ConversationHandler.END

        ctx.user_data["booking"] = {
            "type":    "course",
            "name":    COURSE["name"],
            "teacher": COURSE["teacher"],
            "date":    COURSE["schedule"],
            "price":   COURSE["price"],
            "id":      COURSE["id"],
        }

        keyboard = [[InlineKeyboardButton("Записаться →", callback_data="confirm_course")]]
        await query.edit_message_text(
            f"*{COURSE['name']}*\n"
            f"Преподаватель: {COURSE['teacher']}\n"
            f"Формат: {COURSE['lessons']} · {COURSE['schedule']}\n"
            f"Стоимость: *{COURSE['price']}* за курс\n\n"
            "Программа:\n"
            "1. Простые фигуры · Перспектива\n"
            "2. Тон важнее цвета\n"
            "3. Пропорции человека\n"
            "4. Портрет с нуля",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CHOOSE_SESSION  # ждём подтверждения кнопкой

    else:
        # Свободное рисование — показываем даты
        available = [s for s in FREE_SESSIONS if s["spots"] > 0]
        if not available:
            await query.edit_message_text(
                "Сейчас свободных мест нет 😔\n\n"
                "Напишите нам — появятся новые даты: @otrookibot"
            )
            return ConversationHandler.END

        keyboard = []
        for s in available:
            spots_txt = f"{s['spots']} {_spots_word(s['spots'])}"
            label = f"{s['date']} · {s['time']} · {spots_txt}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"ses:{s['id']}")])

        await query.edit_message_text(
            "*Свободное рисование* с Женей Бородиной\n"
            "5 000 ₽ за вечер · все материалы включены\n\n"
            "Выбирай дату:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CHOOSE_SESSION


# ── Выбор даты (свободное рисование) или подтверждение курса ──
async def session_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "confirm_course":
        # Курс уже в user_data — просто спрашиваем имя
        booking = ctx.user_data.get("booking", {})
        await query.edit_message_text(
            f"Отлично, записываем на *{booking.get('name')}*!\n\n"
            "Как тебя зовут?",
            parse_mode="Markdown",
        )
        return GET_NAME

    # Свободное рисование — выбрали конкретную дату
    session_id = data.split(":", 1)[1]
    session    = next((s for s in FREE_SESSIONS if s["id"] == session_id), None)

    if not session or session["spots"] <= 0:
        await query.edit_message_text("Это место уже занято. Попробуй /start — покажу другие даты.")
        return ConversationHandler.END

    ctx.user_data["booking"] = {
        "type":    "free",
        "name":    "Свободное рисование",
        "teacher": "Женя Бородина",
        "date":    f"{session['date']} · {session['time']}",
        "price":   session["price"],
        "id":      session["id"],
    }

    await query.edit_message_text(
        f"*{session['date']}* в {session['time']}\n"
        "Свободное рисование · Женя Бородина\n\n"
        "Как тебя зовут?",
        parse_mode="Markdown",
    )
    return GET_NAME


# ── Имя → финал ────────────────────────────────────────────
async def get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Напиши своё имя:")
        return GET_NAME

    booking = ctx.user_data.get("booking", {})
    user    = update.effective_user
    tg_ref  = f"@{user.username}" if user.username else f"tg://user?id={user.id}"

    # Уменьшить места
    if booking.get("type") == "free":
        for s in FREE_SESSIONS:
            if s["id"] == booking.get("id"):
                s["spots"] = max(0, s["spots"] - 1)
                break
    else:
        COURSE["spots"] = max(0, COURSE["spots"] - 1)

    # Подтверждение пользователю
    await update.message.reply_text(
        f"Отлично, {name}! Ты записан(а) 🙌\n\n"
        f"📌 *{booking.get('name')}*\n"
        f"🗓 {booking.get('date')}\n"
        f"💳 {booking.get('price')}\n\n"
        f"💸 *Оплата:* переведи на {PAYMENT_BANK} по номеру "
        f"`{PAYMENT_PHONE}` ({PAYMENT_NAME})\n\n"
        f"{ADDRESS}\n\n"
        "Если что-то поменяется — напиши сюда, разберёмся 🙂\n"
        "Есть вопросы — тоже пиши, ответим.\n\n"
        "До встречи ✦",
        parse_mode="Markdown",
    )

    # Уведомление администратору
    admin_msg = (
        f"🆕 *Новая запись!*\n\n"
        f"👤 {name}\n"
        f"🔗 {tg_ref}\n\n"
        f"📌 {booking.get('name')}\n"
        f"🗓 {booking.get('date')}\n"
        f"💳 {booking.get('price')}"
    )
    try:
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
    except Exception as e:
        log.warning("Уведомление администратору: %s", e)

    # Google Sheets
    _append_to_sheet([
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        name,
        tg_ref,
        booking.get("name", ""),
        booking.get("teacher", ""),
        booking.get("date", ""),
        booking.get("price", ""),
    ])

    return ConversationHandler.END


# ── /cancel ─────────────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Окей! Если надумаешь — просто напиши /start 🙂"
    )
    return ConversationHandler.END


# ── Хелпер склонения ────────────────────────────────────────
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
            CHOOSE_PRODUCT: [
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
            ],
            CHOOSE_SESSION: [
                CallbackQueryHandler(session_chosen, pattern=r"^(ses:|confirm_course)"),
            ],
            GET_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    log.info("Бот ОТ РУКИ запущен ✦")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
