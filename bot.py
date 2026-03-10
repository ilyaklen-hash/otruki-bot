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
     "date": "31 марта, вторник",  "time": "19:00", "price": "5 000 ₽", "spots": 10},
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
        [InlineKeyboardButton("📚 Курс «Основы» с 17 марта — узнать первыи",
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
    except FileNotFoundError:
        log.warning("welcome.png не найден, отправляю текстом")
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
    # Пробуем обновить подпись фото; если не получится ℐ s�бновим тeкст
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
            "Запись сещё не о�`�.�`4b�.�,4`tc4/t/�4/4b�4/t,4/�.4b4-t/4`�-t,t-H4/�-t`4,�b�/
4/�.JH<'�c�����&�,4.�4`�-t,tc�4-�/�,�`�`�Ȃ�
B��H[�[�R�^X��\�X\��\
�ؘX��ܛ��
WJB��N��]�Z]]Y\�K�Y]�Y\��Y�W��\[ۊ��\[ۏ]^\��W�[�OH�X\���ۈ��\W�X\��\Z؂�
B�^�\^�\[ێ��]�Z]]Y\�K�Y]�Y\��Y�W�^
�^]^\��W�[�OH�X\���ۈ��\W�X\��\Z؂�
B��]\���UӐSQB���8� 8� 4$�b�,t/�`4-4,4`�b�8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� �]�Z[X�HH���܈�[��T��SӔ�Y��ȝYȗHOHY�[��Ȝ��ȗH�B��Y���]�Z[X�N��XX�\�ۘ[YHH�%�-t/tc�4$�/�`4/�-4.4/t,�Y�Y�OH��[�XH�[�H�'�/�.�.4/t,4+�`4a�-t,�,��^H
���&�4`t/�-�,4.�-t/t.4c�4`t,�/�,t/�-4/tb�aH4/4-t`t`�4`��XX�\�ۘ[Y_H4`t-t.ta�,4`H4/t-t`�<'�%�����'t,4/�.4b4.4/t,4/8�%4/�/�c�,�c�`�`tc�4/t/�,�b�-H4-4,4`�bΈ�����X����
B�؈H[�[�R�^X��\�X\��\
�ؘX��ܛ��
WJB��N��]�Z]]Y\�K�Y]�Y\��Y�W��\[ۊ�\[ۏ]^�\W�X\��\Z؊B�^�\^�\[ێ��]�Z]]Y\�K�Y]�Y\��Y�W�^
^]^�\W�X\��\Z؊B��]\���۝�\��][ے[�\��S����[\HH]�Z[X�V�B��ܛX]ۘ[YHH�[\Vș�ܛX]�B��Y��ܛX]ۘ[YHOH�(t,�/�,t/�-4/t/�-H4`4.4`t/�,�,4/t.4-H���\��H
��$�-ta�-t`4,t-t-�4`t`�`4/�,�/�.H4/�`4/�,�`4,4/4/4b�8�%4,t-t`4dtb4c4`�-t/4`�4.4.�.4`4.4`t`�-tb4c4`t,�/�dK���/�`4-t/�/�-4,4,�,4`�-t.�c4`4c�-4/�/4-t`t.�.4/t`�-�/t,4/�/�/4/�btc�����(�,�/�.�c4/4,4`t.�c�/t,4c�4/�,4`t`�-t.�c4/4,4`t.�c�/tb�-H4.�,4`4,4/t-4,4b4.�4'�/�b�`�4/t-H4/t`�-�-t/K���
B�[�N��\��H
��$4.�,4-4-t/4.4a�-t`t.�.4.H4/�/�-4at/�-�4/�`�4/�-t`4`t/�-t.�`�.4,�b�4-4/�4/�/�`4`�`4-t`�,�����&�,4`4,4/t-4,4b4/4,4`t.�c�/t,4c�4.4`t`�at,4c�4/�,4`t`�-t-�c�4'�/�b�`�4/t-H4/t`�-�-t/K�M�Ȃ�
B���^X��\�H�B��܈�[�]�Z[X�N������H����������_H�������ܙ
�������J_H��X�[H������]I�_H0������[YI�_H0�������H���^X��\��\[�
�[�[�R�^X��\��]ۊX�[�[�X���]OY���\Ξ����Y	�_H�WJB��^X��\��\[�
ؘX��ܛ��
JB���\[ۈH
����ٛܛX]ۘ[Y_J������H8��H0��4,�`t-H4/4,4`�-t`4.4,4.�b�4,�.�.�c�a�-t/tb��������\��W�����$�b�,t-t`4.4`�-4/�,t/tb�.H4,�-ta�-t`���
B�؈H[�[�R�^X��\�X\��\
�^X��\�
B��N��]�Z]]Y\�K�Y]�Y\��Y�W��\[ۊ��\[ۏX�\[ۋ\��W�[�OH�X\���ۈ��\W�X\��\Z؂�
B�^�\^�\[ێ��]�Z]]Y\�K�Y]�Y\��Y�W�^
�^X�\[ۋ\��W�[�OH�X\���ۈ��\W�X\��\Z؂�
B��]\������W��T��Sӂ����8� 8� 4$�b�,t/�`4-4,4`�b�8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� �\�[��Y�����W��\��[ۊ\]N�\]K���۝^\\ˑQ�US�TJHO�[���]Y\�HH\]K��[�X���]Y\�B�]�Z]]Y\�K�[���\�
B���\��[ۗ�YH]Y\�K�]K��]
���JV�WB��\��[ۈH�^

��܈�[��T��SӔ�Y��ȚY�HOH�\��[ۗ�Y
K�ۙJB��Y����\��[ۈ܈�\��[ۖȜ��ȗHH��^H�(�/�`K4.�`�/�t`�/�4`�`t/�-t.�4`4,4/tc4b4-H<'�!W��'t,4-�/4.0����4$�4/t,4a�,4.�/���8�%4/�/�.�,4-�`�4-4`4`�,�.4-H4-4,4`�bˈ��؈H[�[�R�^X��\�X\��\
�ؘX��ܛ��
WJB��N��]�Z]]Y\�K�Y]�Y\��Y�W��\[ۊ�\[ۏ]^�\W�X\��\Z؊B�^�\^�\[ێ��]�Z]]Y\�K�Y]�Y\��Y�W�^
^]^�\W�X\��\Z؊B��]\���۝�\��][ے[�\��S�����\�\��]VȘ����[�ȗHH�\H����\��[ۈ����[YH���\��[ۖș�ܛX]�K��XX�\����\��[ۖȝXX�\��K��]H������\��[ۖ��]I�_H0����\��[ۖ��[YI�_H����X�H���\��[ۖȜ�X�H�K��Y���\��[ۖȚY�K�B�^H
������\��[ۖ��]I�_J�4,���\��[ۖ��[YI�_H8�%4/�`�/4-ta�-t/t/�8�)������&�,4.�4`�-t,tc�4-�/�,�`�`�Ȃ�
B�؈H[�[�R�^X��\�X\��\
�ؘX��ܛ��
WJB��N��]�Z]]Y\�K�Y]�Y\��Y�W��\[ۊ��\[ۏ]^\��W�[�OH�X\���ۈ��\W�X\��\Z؂�
B�^�\^�\[ێ��]�Z]]Y\�K�Y]�Y\��Y�W�^
�^]^\��W�[�OH�X\���ۈ��\W�X\��\Z؂�
B��]\���UӐSQB����8� 8� 4&4/4c�8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� �\�[��Y��]ۘ[YJ\]N�\]K���۝^\\ˑQ�US�TJHO�[����[YHH\]K�Y\��Y�K�^���\

B�Y�[��[YJH���]�Z]\]K�Y\��Y�K��\W�^
�'t,4/�.4b4.4`t,�/�dH4.4/4cΈ�B��]\���UӐSQB����\�\��]Vț�[YH�HH�[YB�����[��H��\�\��]K��]
�����[�ȋ�JB��Y�����[�˙�]
�\H�HOH��Z]\����\��H��ۘ[Y_K4-�,4/�.4`t,4.�.W��'�`t`�,4,�c4/t/�/4-t`8�%4/t,4/�.4b4-t/4.�,4.�4`�/�.�c4.�/�4/�`�.�`4/�-t`�`tc�4-�,4/�.4`tc���[�N��\��H��ۘ[Y_K4/�`4.4c�`�/t/�W��'�`t`�,4,�c4/t/�/4-t`4`�-t.�-ta4/�/t,8�%4/t,4/�.4b4-t/4/t,4/�/�/4.4/t,4/t.4-H4/t,4.�,4/t`�/t-N����]�Z]\]K�Y\��Y�K��\W�^
�\��
�������\�8�%4,�-t`4/t`�`�c4`tc�4,�4,�.�,4,�/t/�-H4/4-t/tc�ȋ�\��W�[�OH�X\���ۈ��
B��]\���U�ӑB����8� 8� 4(�-t.�-ta4/�/H8���4a4.4/t,4.�8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� 8� �\�[��Y��]�ۙJ\]N�\]K���۝^\\ˑQ�US�TJHO�[���ۙHH\]K�Y\��Y�K�^���\

B��[YHH��\�\��]K��]
��[YH���%�B�����[��H��\�\��]K��]
�����[�ȋ�JB�\�\�H\]K�Y��X�]�W�\�\���ܙY�H���\�\��\�\��[Y_H�Y�\�\��\�\��[YH[�H��Y�\�\��YH���Y�����[�˙�]
�\H�HOH��Z]\����]�Z]\]K�Y\��Y�K��\W�^
��%�,4/�.4`t,4.�.4`�b�4,�4/�-t`4,�/�/4`t/�.4`t.�-H<'�c�����&�,4.�4`�/�.�c4.�/�4.�`�`4`H4,t`�-4-t`�4,�/�`�/�,�8�%4/t,4/�.4b4-t/4`t`4,4-�`�4`H4/�`4/�,�`4,4/4/4/�.H4.4-4,4`�,4/4.������%t`tc вопросы — пиши прямо сюда 🙂",
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
            "Если чтп-то поменялось или есть вопросы — просто напиши сюда 🙂",
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
    text   = update.message.text or "(не текст)"

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
