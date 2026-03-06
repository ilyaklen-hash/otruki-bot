#!/usr/bin/env python3
"""
ОТ РУКИ — Telegram-бот для записи на занятия
==============================================

Установка:
    pip install "python-telegram-bot[socks]" gspread google-auth

Запуск:
    python bot.py

Флоу:
    /start → выбор продукта → (дата) → имя → телефон → подтверждение
    Вопросы вне флоу → пересылаются администратору
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

try:
    import gspread
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# ═══════════════════════════════════════════════════════════
#  НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════

BOT_TOKEN = "8771338517:AAEs0mfa_cPoWKySsFXLkWQb3DNKjO8c4Z0"
ADMIN_ID  = 163103731  # @klenklen

ADDRESS = (
    "📍 Большой Сергиевский переулок, 11\n"
    "Домофон: 9300, код вызова 12\n"
    "5 этаж, кв. 12"
)

PAYMENT_PHONE = "+7 926 115 3033"
PAYMENT_NAME  = "Михаил Г."
PAYMENT_BANK  = "Т-Банк"

# ID таблицы из URL: .../spreadsheets/d/<ID>/edit
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# ═══════════════════════════════════════════════════════════
#  ПРОДУКТЫ  ← обновляйте перед каждым набором
# ═══════════════════════════════════════════════════════════

# Курс — только понедельники, 4 занятия
COURSE = {
    "id":      "course",
    "name":    "Курс «Основы рисования»",
    "teacher": "Полина Ярцева",
    "schedule": "Понедельник · 19:00 · старт 25 марта · 4 занятия",
    "price":   "20 000 ₽",
    "spots":   10,
}

# Свободное рисование — только предстоящая неделя
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

CHOOSE_PRODUCT, CHOOSE_SESSION, GET_NAME, GET_PHONE = range(4)


# ── Google Sheets ───────────────────────────────────────────
def _append_to_sheet(row: list) -> None:
    if not GSPREAD_AVAILABLE:
        log.warning("Google Sheets: gspread не установлен")
        return
    if not GOOGLE_SHEET_ID:
        log.warning("Google Sheets: GOOGLE_SHEET_ID не задан")
        return
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if not creds_json:
        log.warning("Google Sheets: GOOGLE_CREDENTIALS не задан")
        return
    try:
        try:
            creds_data = json.loads(creds_json)
        except json.JSONDecodeError:
            # Railway иногда хранит реальные \n вместо \\n в private_key
            creds_data = json.loads(creds_json.replace('\n', '\\n'))
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        # service_account_from_dict — правильный способ в gspread 6.x
        gc = gspread.service_account_from_dict(creds_data, scopes=scopes)
        ws = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        # Заголовки — только если лист пустой
        if not ws.get_all_values():
            ws.append_row([
                "Дата записи", "Имя", "Телефон", "Telegram",
                "Занятие", "Преподаватель", "Дата занятия", "Цена"
            ])
        ws.append_row(row)
        log.info("Google Sheets: запись добавлена")
    except Exception as e:
        log.error("Google Sheets: %s", e)


# ── /start ──────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("🎨 Свободное рисование  · 5 000 ₽", callback_data="product:free")],
        [InlineKeyboardButton("📚 Курс «Основы рисования»  · 20 000 ₽", callback_data="product:course")],
    ]
    await update.message.reply_text(
        "Привет! Это *ОТ РУКИ* — школа графики в Москве 🎨\n\n"
        "Рисуем в мастерской Миши Ганнушкина, небольшими группами. "
        "Все материалы включены, нужно только желание.\n\n"
        "Есть два формата — выбирай что ближе:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSE_PRODUCT


# ── Выбор продукта ──────────────────────────────────────────
async def choose_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    product = query.data.split(":", 1)[1]

    if product == "course":
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
            f"{COURSE['schedule']}\n"
            f"Стоимость: *{COURSE['price']}*\n\n"
            "Программа:\n"
            "1. Простые фигуры · Перспектива\n"
            "2. Тон важнее цвета\n"
            "3. Пропорции человека\n"
            "4. Портрет с нуля",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CHOOSE_SESSION

    else:
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


# ── Выбор даты / подтверждение курса ────────────────────────
async def session_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "confirm_course":
        booking = ctx.user_data.get("booking", {})
        await query.edit_message_text(
            f"Отлично, записываем на *{booking.get('name')}*!\n\n"
            "Как тебя зовут?",
            parse_mode="Markdown",
        )
        return GET_NAME

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


# ── Имя ─────────────────────────────────────────────────────
async def get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Напиши своё имя:")
        return GET_NAME

    ctx.user_data["name"] = name
    await update.message.reply_text(
        f"Приятно, {name}! Оставь номер телефона — пришлём напоминание накануне:"
    )
    return GET_PHONE


# ── Телефон → финал ─────────────────────────────────────────
async def get_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    phone   = update.message.text.strip()
    name    = ctx.user_data.get("name", "—")
    booking = ctx.user_data.get("booking", {})
    user    = update.effective_user
    tg_ref  = f"@{user.username}" if user.username else f"id{user.id}"

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
        f"Ты записан(а) 🙌\n\n"
        f"📌 *{booking.get('name')}*\n"
        f"🗓 {booking.get('date')}\n"
        f"💳 {booking.get('price')}\n\n"
        f"💸 *Оплата:* переведи на {PAYMENT_BANK} по номеру "
        f"`{PAYMENT_PHONE}` ({PAYMENT_NAME})\n\n"
        f"{ADDRESS}\n\n"
        "Если что-то поменяется или есть вопросы — напиши сюда, ответим 🙂\n\n"
        "До встречи ✦",
        parse_mode="Markdown",
    )

    # Уведомление администратору
    admin_msg = (
        f"🆕 *Новая запись!*\n\n"
        f"👤 {name}\n"
        f"📞 {phone}\n"
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
        phone,
        tg_ref,
        booking.get("name", ""),
        booking.get("teacher", ""),
        booking.get("date", ""),
        booking.get("price", ""),
    ])

    return ConversationHandler.END


# ── /cancel ─────────────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Окей! Если надумаешь — просто напиши /start 🙂")
    return ConversationHandler.END


# ── Вопросы вне флоу → пересылаем администратору ────────────
async def forward_question(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    tg_ref = f"@{user.username}" if user.username else f"id{user.id}"
    text = update.message.text or "(не текст)"

    await update.message.reply_text(
        "Получили! Ответим в ближайшее время 🙂\n\n"
        "Если хочешь записаться — нажми /start"
    )
    try:
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💬 *Вопрос от {tg_ref}*\n\n{text}",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning("Пересылка вопроса: %s", e)


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
            GET_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    # Всё остальное (вопросы) — пересылаем администратору
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_question))

    log.info("Бот ОТ РУКИ запущен ✦")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
