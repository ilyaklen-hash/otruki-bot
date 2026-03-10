#!/usr/bin/env python3
"""
ОТ РУКИ — Telegram-бот для записи на занятия
==============================================

Флоу:
    /start → фото + выбор формата → дата → имя → телефон → подтверждение
    Кнопка «Курс» → имя → телефон → лист ожидания
    Вопросы вне флоу → пересылаются администратору
    Кнопка «← В начало» / команда /start — перезапуск в любой момент
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

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# Путь к приветственному фото (рядом с bot.py)
WELCOME_PHOTO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "welcome.png")

# ═══════════════════════════════════════════════════════════
#  ЗАНЯТИЯ  ← обновляйте перед каждым новым месяцем
# ═══════════════════════════════════════════════════════════

SESSIONS = [
    # ── Женя Бородина — понедельник / среда ─────────────────
    {"id": "e1", "tag": "zhenya", "teacher": "Женя Бородина",
     "format": "Свободное рисование",
     "date": "16 марта, понедельник", "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "e2", "tag": "zhenya", "teacher": "Женя Бородина",
     "format": "Свободное рисование",
     "date": "18 марта, среда",       "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "e3", "tag": "zhenya", "teacher": "Женя Бородина",
     "format": "Свободное рисование",
     "date": "23 марта, понедельник", "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "e4", "tag": "zhenya", "teacher": "Женя Бородина",
     "format": "Свободное рисование",
     "date": "25 марта, среда",       "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "e5", "tag": "zhenya", "teacher": "Женя Бородина",
     "format": "Свободное рисование",
     "date": "30 марта, понедельник", "time": "19:00", "price": "5 000 ₽", "spots": 10},

    # ── Полина Ярцева — вторник / четверг ───────────────────
    {"id": "p1", "tag": "polina", "teacher": "Полина Ярцева",
     "format": "Основы рисования",
     "date": "17 марта, вторник",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "p2", "tag": "polina", "teacher": "Полина Ярцева",
     "format": "Основы рисования",
     "date": "19 марта, четверг",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "p3", "tag": "polina", "teacher": "Полина Ярцева",
     "format": "Основы рисования",
     "date": "24 марта, вторник",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "p4", "tag": "polina", "teacher": "Полина Ярцева",
     "format": "Основы рисования",
     "date": "26 марта, четверг",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
    {"id": "p5", "tag": "polina", "teacher": "Полина Ярцева",
     "format": "Основы рисования",
 0   "date": "31 марта, вторник",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
]

# ═══════════════════════════════════════════════════════════
#  КОД БОТА
# ═══════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

CHOOSE_TEACHER, CHOOSE_SESSION, GET_NAME, GET_PHONE = range(4)


# ── Вспомогательные ─────────────────────────────────────────

def _main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 Свободное рисование · пн и ср · 5 000 ₽",
                              callback_data="teacher:zhenya")],
        [InlineKeyboardButton("✏️ Основы рисования · вт и чт · 5 000 ₽",
                              callback_data="teacher:polina")],
        [InlineKeyboardButton("📚 Курс «Основы» с 17 марта — узнать первым",
                              callback_data="teacher:waitlist")],
    ])

def _back_row():
    """Строка с кнопкой «В начало» — добавляем к любой клавиатуре."""
    return [InlineKeyboardButton("← В начало", callback_data="back_to_start")]

WELCOME_TEXT = (
    "Привет! Это школа графики *ОТ РУКИ* 🎨\n\n"
    "Сейчас проводим разовые вечерние занятия — небольшие группы, "
    "живая атмосфера мастерской. Все материалы включены.\n\n"
    "Выбери для себя комфортную форму обучения, день и время:"
)


# ── Google Sheets ────────────────────────────────────────────
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
            creds_data = json.loads(creds_json.replace('\n', '\\n'))
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        gc = gspread.service_account_from_dict(creds_data, scopes=scopes)
        ws = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        if not ws.get_all_values():
            ws.append_row([
                "Дата записи", "Имя", "Телефон", "Telegram",
                "Формат", "Преподаватель", "Дата занятия", "Цена"
            ])
        ws.append_row(row)
        log.info("Google Sheets: запись добавлена")
    except Exception as e:
        log.error("Google Sheets: %s", e)


# ── /start ───────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Отправляет приветственное фото с текстом и кнопками."""
    kb = _main_keyboard()
    try:
        with open(WELCOME_PHOTO, "rb") as photo_file:
            await update.message.reply_photo(
                photo=photo_file,
                caption=WELCOME_TEXT,
                parse_mode="Markdown",
                reply_markup=kb,
            )
    except Exception:
        log.warning("welcome.png: ошибка отправки фото, отправляю текстом")
        await update.message.reply_text(
            WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    return CHOOSE_TEACHER


# ── ← В начало (callback) ────────────────────────────────────
async def back_to_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Возвращает в главное меню из любого шага."""
    query = update.callback_query
    await query.answer()
    kb = _main_keyboard()
    # Пробуем обновить подпись фотп; если не получится — обновим текст
    try:
        await query.edit_message_caption(
            caption=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception:
        try:
            await query.edit_message_text(
                text=WELCOME_TEXT,
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception:
            # Сообщение не изменилось — отправим новое
            await query.message.reply_text(
                WELCOME_TEXT,
                parse_mode="Markdown",
                reply_markup=kb,
            )
    return CHOOSE_TEACHER


# ── Выбор формата ────────────────────────────────────────────
async def choose_teacher(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    tag = query.data.split(":", 1)[1]

    # ── Лист ожидания курса ──────────────────────────────────
    if tag == "waitlist":
        ctx.user_data["booking"] = {
            "type":    "waitlist",
            "name":    "Курс «Основы рисования»",
            "teacher": "Полина Ярцева",
            "date":    "с 17 марта",
            "price":   "20 000 ₽",
            "id":      "waitlist",
        }
        text = (
            "*Курс «Основы рисования»* — 4 занятия подряд:\n"
            "перспектива → форма → свет → портрет.\n\n"
            "Запись ещё не открылась, но мы напишем тебе первым(ой) 🙌\n\n"
            "Как тебя зовут?"
        )
        kb = InlineKeyboardMarkup([_back_row()])
        try:
            await query.edit_message_caption(
                caption=text, parse_mode="Markdown", reply_markup=kb
            )
        except Exception:
            await query.edit_message_text(
                text=text, parse_mode="Markdown", reply_markup=kb
            )
        return GET_NAME

    # ── Выбор даты ───────────────────────────────────────────
    available = [s for s in SESSIONS if s["tag"] == tag and s["spots"] > 0]

    if not available:
        teacher_name = "Женя Бородина" if tag == "zhenya" else "Полина Ярцева"
        text = (
            f"К сожалению, свободных мест у {teacher_name} сейчас нет 😔\n\n"
            "Напиши нам — появятся новые даты: @otrookibot"
        )
        kb = InlineKeyboardMarkup([_back_row()])
        try:
            await query.edit_message_caption(caption=text, reply_markup=kb)
        except Exception:
            await query.edit_message_text(text=text, reply_markup=kb)
        return ConversationHandler.END

    sample      = available[0]
    format_name = sample["format"]

    if format_name == "Свободное рисование":
        desc = (
            "Вечер без строгой программы — берёшь тему или рисуешь своё, "
            "преподаватель рядом если нужна помощь.\n"
            "Уголь, масляная пастель, масляные карандаш��. Опыэ не нужен."
        )
    else:
        desc = (
            "Академический подход: от перспективы до портрета.\n"
            "Карандаш, масляная и сухая пастель. Опыт не нужен. 16+"
        )

    keyboard = []
    for s in available:
        spots_txt = f"{s['spots']} {_spots_word(s['spots'])}"
        label = f"{s['date']} · {s['time']} · {spots_txt}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"ses:{s['id']}")])
    keyboard.append(_back_row())

    caption = (
        f"*{format_name}*\n"
        f"5 000 ₽ · все материалы включены\n\n"
        f"{desc}\n\n"
        "Выбери удобный вечер:"
    )
    kb = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_caption(
            caption=caption, parse_mode="Markdown", reply_markup=kb
        )
    except Exception:
        await query.edit_message_text(
            text=caption, parse_mode="Markdown", reply_markup=kb
        )
    return CHOOSE_SESSION


# ── Выбор даты ───────────────────────────────────────────────
async def choose_session(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    session_id = query.data.split(":", 1)[1]
    session = next((s for s in SESSIONS if s["id"] == session_id), None)

    if not session or session["spots"] <= 0:
        text = "Упс, кто-то успел раньше 😅\n\nНажми «← В начало» — покажу другие даты."
        kb = InlineKeyboardMarkup([_back_row()])
        try:
            await query.edit_message_caption(caption=text, reply_markup=kb)
        except Exception:
            await query.edit_message_text(text=text, reply_markup=kb)
        return ConversationHandler.END

    ctx.user_data["booking"] = {
        "type":    "session",
        "name":    session["format"],
        "teacher": session["teacher"],
        "date":    f"{session['date']} · {session['time']}",
        "price":   session["price"],
        "id":      session["id"],
    }
    text = (
        f"*{session['date']}* в {session['time']} — отмечено ✦\n\n"
        "Как тебя зовуе?"
    )
    kb = InlineKeyboardMarkup([_back_row()])
    try:
        await query.edit_message_caption(
            caption=text, parse_mode="Markdown", reply_markup=kb
        )
    except Exception:
        await query.edit_message_text(
            text=text, parse_mode="Markdown", reply_markup=kb
        )
    return GET_NAME


# ── Имя ──────────────────────────────────────────────────────
async def get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Напиши своё имя:")
        return GET_NAME

    ctx.user_data["name"] = name
    booking = ctx.user_data.get("booking", {})

    if booking.get("type") == "waitlist":
        msg = f"{name}, записали!\n\nОставь номер — напишем, как только откроется запись:"
    else:
        msg = f"{name}, приятно!\n\nОставь номер телефона — напишем напоминание накануне:"

    await update.message.reply_text(
        msg + "\n\n_/start — вернуться в главное меню_",
        parse_mode="Markdown",
    )
    return GET_PHONE


# ── Телефон → финал ──────────────────────────────────────────
async def get_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    phone   = update.message.text.strip()
    name    = ctx.user_data.get("name", "—")
    booking = ctx.user_data.get("booking", {})
    user    = update.effective_user
    tg_ref  = f"@{user.username}" if user.username else f"id{user.id}"

    if booking.get("type") == "waitlist":
        await update.message.reply_text(
            "Записали, ты в первом списке 🙌\n\n"
            "Как только курс будет готов — напишем сразу, с программой и датами.\n\n"
 (          "Есть вопросы — пиши прямо сюда 🙂",
        )
        admin_msg = (
            f"📋 *Лист ожидания — Курс с Полиной*\n\n"
            f"👤 {name}\n"
            f"📞 {phone}\n"
            f"🔗 {tg_ref}"
        )
    else:
        # Уменьшаем количество мест
        for s in SESSIONS:
            if s["id"] == booking.get("id"):
                s["spots"] = max(0, s["spots"] - 1)
                break

        await update.message.reply_text(
            f"Всё, ждём тебя ✦\n\n"
            f"📌 *{booking.get('name')}*\n"
            f"🗓 {booking.get('date')}\n"
            f"💳 {booking.get('price')}\n\n"
            f"💸 *Оплата:* переведи на {PAYMENT_BANK} по номеру "
            f"`{PAYMENT_PHONE}` ({PAYMENT_NAME})\n\n"
            f"{ADDRESS}\n\n"
            "Если что-то поменялось или есть вопросы — просто напиши сюда 🙂",
            parse_mode="Markdown",
        )
        admin_msg = (
            f"🆕 *Новая запись!*\n\n"
            f"👤 {name}\n"
            f"📞 {phone}\n"
            f"🔗 {tg_ref}\n\n"
            f"📌 {booking.get('name')} · {booking.get('teacher')}\n"
            f"🗓 {booking.get('date')}\n"
            f"💳 {booking.get('price')}"
        )

    # Уведомление администратору
    try:
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
    except Exception as e:
        log.warning("Уведомление администратору: %s", e)

    # Google Sheets
    _append_to_sheet([
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        name, phone, tg_ref,
        booking.get("name", ""),
        booking.get("teacher", ""),
        booking.get("date", ""),
        booking.get("price", ""),
    ])

    return ConversationHandler.END


# ── /cancel ──────────────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Окей, без проблем. Передумаешь — /start 🙂")
    return ConversationHandler.END


# ── Вопросы вне флоу ─────────────────────────────────────────
async def forward_question(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user   = update.effective_user
    tg_ref = f"@{user.username}" if user.username else f"id{user.id}"
    text   = update.message.text or "(не секст)"

    await update.message.reply_text(
        "Увидели, ответим скоро 🙂\n\n"
        "Хочешь записаться — /start"
    )
    try:
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💬 *Вопрос от {tg_ref}*\n\n{text}",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning("Пересылка вопроса: %s", e)


# ── Склонение ─────────────────────────────────────────────────
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

    back_handler = CallbackQueryHandler(back_to_start, pattern=r"^back_to_start$")

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_TEACHER: [
                CallbackQueryHandler(choose_teacher, pattern=r"^teacher:"),
                back_handler,
            ],
            CHOOSE_SESSION: [
                CallbackQueryHandler(choose_session, pattern=r"^ses:"),
                back_handler,
            ],
            GET_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_name),
                back_handler,
            ],
            GET_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
                back_handler,
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),   # /start перезапускает в любой момент
        ],
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_question))

    log.info("Бот ОТ РУКИ запущен ✦")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
