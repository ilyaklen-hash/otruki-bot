#!/usr/bin/env python3
"""
ОТ РУКИ — Telegram-бот для записи на занятия
==============================================

Установка:
    pip install python-telegram-bot

Запуск:
    python bot.py

Что делает бот:
    1. Встречает нового пользователя
    2. Показывает ближайшие занятия
    3. Принимает запись: имя → контакт
    4. Отправляет подтверждение клиенту
    5. Уведомляет администратора о новой записи
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes,
)

# ═══════════════════════════════════════════════════════════
#  НАСТРОЙКИ — заполнить перед запуском
# ═══════════════════════════════════════════════════════════

BOT_TOKEN = "8771338517:AAEs0mfa_cPoWKySsFXLkWQb3DNKjO8c4Z0"

ADMIN_ID = 163103731  # @klenklen

# ═══════════════════════════════════════════════════════════
#  РАСПИСАНИЕ ЗАНЯТИЙ
#  Обновляйте этот список перед каждым набором
# ═══════════════════════════════════════════════════════════

SESSIONS = [
    {
        "id":    "s1",
        "date":  "15 марта, суббота",
        "time":  "19:00",
        "theme": "Натюрморт",
        "spots": 5,
    },
    {
        "id":    "s2",
        "date":  "22 марта, суббота",
        "time":  "19:00",
        "theme": "Портрет",
        "spots": 6,
    },
    {
        "id":    "s3",
        "date":  "29 марта, суббота",
        "time":  "19:00",
        "theme": "Абстракция",
        "spots": 4,
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

# Состояния диалога
CHOOSE_SESSION, GET_NAME, GET_PHONE = range(3)


# ── /start ────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[
        InlineKeyboardButton("📅 Посмотреть занятия", callback_data="show_sessions"),
    ]]
    await update.message.reply_text(
        "Привет! Это *ОТ РУКИ* — вечера рисования для взрослых 🎨\n\n"
        "Мы собираемся небольшой группой дома у художника, "
        "2,5 часа рисуем вместе. Все материалы включены.\n\n"
        "Стоимость: *3 500 ₽* за занятие",
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
        label = f"{s['date']} · {s['theme']} · {spots_txt}"
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
        f"🎨 Тема: *{session['theme']}*\n\n"
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
        f"🎨 Тема: {session.get('theme')}\n\n"
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
        f"🎨 {session.get('theme')}"
    )
    try:
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
    except Exception as e:
        log.warning("Не удалось отправить уведомление администратору: %s", e)

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
