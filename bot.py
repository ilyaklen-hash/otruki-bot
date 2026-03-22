#!/usr/bin/env python3
"""
ОТ РУКИ — Telegram-бот для записи на занятия (упрощённый)
Флоу: /start → формат → дата → имя → телефон → ссылка на оплату + адрес
"""

import logging, os, json
from datetime import datetime, timedelta
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

# ═══════════════ НАСТРОЙКИ ═══════════════

BOT_TOKEN = "8771338517:AAEs0mfa_cPoWKySsFXLkWQb3DNKjO8c4Z0"
ADMIN_ID  = 163103731  # @klenklen

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

ADDRESS = (
    "📍 Большой Сергиевский переулок, 11\n"
    "Домофон: 12к9300\n"
    "5 этаж, кв. 12"
)

PAYMENT = {
    "tuesday": {
        "title": "Основы рисования",
        "url": "https://yookassa.ru/my/i/acBU6AXB58Ba/l",
        "weekday": 1,  # 0=пн, 1=вт, 2=ср...
        "label": "вторник",
    },
    "wednesday": {
        "title": "Свободное рисование",
        "url": "https://yookassa.ru/my/i/acBVMiAtpsMf/l",
        "weekday": 2,
        "label": "среда",
    },
}

WEEKDAY_RU = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
MONTH_RU = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"]

def next_dates(weekday: int, count: int = 3) -> list[datetime]:
    """Ближайшие `count` дат нужного дня недели."""
    today = datetime.now().date()
    days_ahead = (weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    dates = []
    d = today + timedelta(days=days_ahead)
    for _ in range(count):
        dates.append(d)
        d += timedelta(weeks=1)
    return dates

def fmt_date(d) -> str:
    return f"{d.day} {MONTH_RU[d.month]}, {WEEKDAY_RU[d.weekday()]}"

# ═══════════════ КОД БОТА ═══════════════

logging.basicConfig(format="%(asctime)s %(levelname)-8s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

CHOOSE_FORMAT, CHOOSE_DATE, GET_NAME, GET_PHONE = range(4)

WELCOME_TEXT = (
    "Привет! Это школа графики *ОТ РУКИ* 🎨\n\n"
    "Небольшие группы, живая атмосфера мастерской. Все материалы включены.\n\n"
    "Выбери направление:"
)

def _format_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Вторник · Основы рисования · 5 000 ₽", callback_data="format:tuesday")],
        [InlineKeyboardButton("🎨 Среда · Свободное рисование · 5 000 ₽",  callback_data="format:wednesday")],
    ])


# ── /start ──────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown",
                                    reply_markup=_format_keyboard())
    return CHOOSE_FORMAT


# ── Выбор формата → показать даты ──────
async def choose_format(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    key = query.data.split(":")[1]
    fmt = PAYMENT[key]
    ctx.user_data["format_key"] = key

    dates = next_dates(fmt["weekday"], 3)
    buttons = []
    for d in dates:
        label = fmt_date(d)
        buttons.append([InlineKeyboardButton(label, callback_data=f"date:{d.isoformat()}")])
    buttons.append([InlineKeyboardButton("← Назад", callback_data="back")])

    text = f"*{fmt['title']}*\n\nВыбери удобную дату:"
    try:
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSE_DATE


# ── Выбор даты → имя ───────────────────
async def choose_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    date_str = query.data.split(":")[1]
    ctx.user_data["date"] = date_str
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    ctx.user_data["date_label"] = fmt_date(d)

    text = f"Отлично, *{fmt_date(d)}* ✦\n\nКак тебя зовут?"
    try:
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("← Назад", callback_data="back")]]))
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown")
    return GET_NAME


# ── Имя → телефон ──────────────────────
async def get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Напиши своё имя:")
        return GET_NAME
    ctx.user_data["name"] = name
    await update.message.reply_text(
        f"{name}, приятно! Оставь номер телефона:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← В начало", callback_data="back")]])
    )
    return GET_PHONE


# ── Телефон → финал ────────────────────
async def get_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    name  = ctx.user_data.get("name", "—")
    key   = ctx.user_data.get("format_key", "tuesday")
    fmt   = PAYMENT[key]
    date_label = ctx.user_data.get("date_label", "")
    user  = update.effective_user
    tg    = f"@{user.username}" if user.username else f"id{user.id}"

    # Сообщение пользователю
    await update.message.reply_text(
        f"Записали, ждём тебя ✦\n\n"
        f"📌 *{fmt['title']}*\n"
        f"🗓 {date_label} · 19:00\n\n"
        f"💳 *Оплата:*\n{fmt['url']}\n\n"
        f"{ADDRESS}\n\n"
        "Если что-то изменилось — просто напиши сюда 🙂",
        parse_mode="Markdown",
    )

    # Уведомление администратору
    try:
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆕 *Новая запись!*\n\n👤 {name}\n📞 {phone}\n🔗 {tg}\n\n"
                 f"📌 {fmt['title']}\n🗓 {date_label}",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning("Уведомление администратору: %s", e)

    # Google Sheets
    _append_to_sheet([
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        name, phone, tg, fmt["title"], date_label,
    ])

    return ConversationHandler.END


# ── Назад ──────────────────────────────
async def back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(WELCOME_TEXT, parse_mode="Markdown",
                                      reply_markup=_format_keyboard())
    except Exception:
        await query.message.reply_text(WELCOME_TEXT, parse_mode="Markdown",
                                       reply_markup=_format_keyboard())
    return CHOOSE_FORMAT


# ── Вопросы вне флоу ───────────────────
async def forward_question(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    tg   = f"@{user.username}" if user.username else f"id{user.id}"
    await update.message.reply_text("Увидели, ответим скоро 🙂\n\nЗаписаться — /start")
    try:
        await ctx.bot.send_message(ADMIN_ID,
            f"💬 *Вопрос от {tg}*\n\n{update.message.text or '(не текст)'}",
            parse_mode="Markdown")
    except Exception as e:
        log.warning("Пересылка вопроса: %s", e)


# ── Google Sheets ───────────────────────
def _append_to_sheet(row: list) -> None:
    if not GSPREAD_AVAILABLE or not GOOGLE_SHEET_ID:
        return
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if not creds_json:
        return
    try:
        try:
            data = json.loads(creds_json)
        except json.JSONDecodeError:
            data = json.loads(creds_json.replace('\n', '\\n'))
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        gc = gspread.service_account_from_dict(data, scopes=scopes)
        ws = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        if not ws.get_all_values():
            ws.append_row(["Дата записи", "Имя", "Телефон", "Telegram", "Формат", "Дата занятия"])
        ws.append_row(row)
    except Exception as e:
        log.error("Google Sheets: %s", e)


# ═══════════════ ЗАПУСК ═══════════════

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_FORMAT: [CallbackQueryHandler(choose_format, pattern=r"^format:"),
                            CallbackQueryHandler(back, pattern=r"^back$")],
            CHOOSE_DATE:   [CallbackQueryHandler(choose_date, pattern=r"^date:"),
                            CallbackQueryHandler(back, pattern=r"^back$")],
            GET_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name),
                            CallbackQueryHandler(back, pattern=r"^back$")],
            GET_PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
                            CallbackQueryHandler(back, pattern=r"^back$")],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_question))

    log.info("Бот ОТ РУКИ запущен ✦")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
