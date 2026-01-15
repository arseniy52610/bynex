import os
import re
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.error import BadRequest
from mistralai.client import MistralClient

# ================= CONFIG =================

TELEGRAM_TOKEN = "8577515890:AAFlBSqsjpq5eE1oHlCtTZjtxb38_LZ8MS8"
MISTRAL_API_KEY = "kBRWeCcqICY8Q20fKADOAE6HxZ07OeU6"
ADMIN_CHAT_ID = 1947766225

MEMORY_FILE = "memory.txt"
PHOTO_FOLDER = "photos"

# =========================================

logging.basicConfig(level=logging.CRITICAL)

mistral = MistralClient(api_key=MISTRAL_API_KEY)

operator_sessions = {}
dialog_history = {}
awaiting_photo = {}

TRANSFER_PHRASES = [
    "я перевожу вас на оператора",
    "перевожу вас на оператора",
    "соединяю вас с оператором",
    "передаю вас оператору"
]

# ================= UTILS =================

def is_real_transfer(text: str) -> bool:
    return any(p in text.lower() for p in TRANSFER_PHRASES)

def load_memory() -> str:
    if not os.path.exists(MEMORY_FILE):
        return ""
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return f.read()

def markdown_to_html(text: str) -> str:
    return re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)

def add_history(user_id: int, role: str, text: str):
    dialog_history.setdefault(user_id, [])
    dialog_history[user_id].append((role, text))

def format_history(user_id: int) -> str:
    history = dialog_history.get(user_id, [])

    lines = [
        f"<b>История диалога (<code>{user_id}</code>)</b>",
        "<blockquote expandable=\"true\">"
    ]

    buffer_role = None
    buffer_text = []

    def flush():
        if not buffer_text:
            return
        title = "👤 <b>Пользователь:</b>" if buffer_role == "user" else "🤖 <b>ИИ:</b>"
        lines.append(f"{title}\n" + "\n".join(buffer_text) + "\n")

    for role, text in history:
        clean = markdown_to_html(text.strip())
        if role == buffer_role:
            buffer_text.append(clean)
        else:
            flush()
            buffer_role = role
            buffer_text = [clean]

    flush()
    lines.append("</blockquote>")
    return "\n".join(lines)

async def send_history_to_admin(context, user_id: int):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=format_history(user_id),
            parse_mode="HTML"
        )
    except BadRequest:
        pass

def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Наш Telegram-канал", url="https://t.me/bynexvpn")]
    ])

# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>👋 Добро пожаловать в службу технической поддержки BynexVPN</b>\n\n"
        "Мы рады помочь вам!\n"
        "Пожалуйста, подробно опишите ваш вопрос или возникшую проблему — наша команда постарается разобраться в ситуации и предложить оптимальное решение в кратчайшие сроки.\n\n"
        "Спасибо, что выбираете BynexVPN 💙\n"
        "Мы всегда на связи и готовы помочь.",
        reply_markup=start_keyboard(),
        parse_mode="HTML"
    )

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    add_history(user_id, "user", text)

    if user_id in operator_sessions:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"<b>Сообщение от <code>{user_id}</code>:</b>\n<blockquote>{text}</blockquote>",
                parse_mode="HTML"
            )
        except BadRequest:
            pass
        return

    if any(w in text.lower() for w in ["оператор", "человек", "поддержка"]):
        operator_sessions[user_id] = True
        await send_history_to_admin(context, user_id)
        await update.message.reply_text(
            "<b>Я передал ваш вопрос оператору.</b>\n<blockquote>График: c 10:00 до 00:00 по МСК</blockquote>",
            parse_mode="HTML"
        )
        return

    await context.bot.send_chat_action(chat_id=user_id, action="typing")

    try:
        response = mistral.chat(
            model="mistral-large-latest",
            messages=[
                {"role": "system", "content": load_memory()},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )

        answer = response.choices[0].message.content.strip()
        add_history(user_id, "ai", answer)

        await update.message.reply_text(
            markdown_to_html(answer),
            parse_mode="HTML"
        )

        if "пришлите" in answer.lower() and ("фото" in answer.lower() or "скрин" in answer.lower()):
            awaiting_photo[user_id] = True

        if is_real_transfer(answer):
            operator_sessions[user_id] = True
            await send_history_to_admin(context, user_id)

    except Exception:
        operator_sessions[user_id] = True
        await update.message.reply_text(
            "Извините, я не понял ваш вопрос. Перевожу вас на оператора.\n\n<blockquote>График: c 10:00 до 00:00 по МСК</blockquote>",
            parse_mode="HTML"
        )
        await send_history_to_admin(context, user_id)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    os.makedirs(PHOTO_FOLDER, exist_ok=True)

    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"{PHOTO_FOLDER}/{user_id}_{file.file_id}.jpg"
    await file.download_to_drive(path)

    if awaiting_photo.get(user_id):
        awaiting_photo.pop(user_id, None)
        operator_sessions[user_id] = True

        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=open(path, "rb"),
            caption=f"<b>Скриншот от <code>{user_id}</code></b>",
            parse_mode="HTML"
        )
        await send_history_to_admin(context, user_id)

        await update.message.reply_text(
            "<b>Фото получено, передал оператору.\nОжидайте ответа!</b>",
            parse_mode="HTML"
        )
        return

    if user_id in operator_sessions:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=open(path, "rb"),
            caption=f"<b>Фото от <code>{user_id}</code></b>",
            parse_mode="HTML"
        )
        return

    await update.message.reply_text(
        "Фото получено. Опишите проблему текстом.",
        parse_mode="HTML"
    )

# ================= ADMIN =================

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != ADMIN_CHAT_ID:
        return

    if len(context.args) < 2:
        return

    user_id = int(context.args[0])
    text = " ".join(context.args[1:])

    if user_id not in operator_sessions:
        return

    await context.bot.send_message(
        chat_id=user_id,
        text=f"<b>👨‍💻 Оператор | BynexVPN </b>\n<blockquote>{text}</blockquote>",
        parse_mode="HTML"
    )

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != ADMIN_CHAT_ID:
        return

    user_id = int(context.args[0])

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Хорошо 👌", callback_data=f"dialog_ok:{user_id}")]
    ])

    await context.bot.send_message(
        chat_id=user_id,
        text="<b>Диалог завершён.</b>\nЕсли появятся вопросы — пишите 🤖",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def dialog_ok_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split(":")[1])

    operator_sessions.pop(user_id, None)
    dialog_history.pop(user_id, None)
    awaiting_photo.pop(user_id, None)

    try:
        await query.message.delete()
    except:
        pass

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "<b>👋 Добро пожаловать в службу технической поддержки BynexVPN</b>\n\n"
            "Мы рады помочь вам!\n"
            "Пожалуйста, подробно опишите ваш вопрос или возникшую проблему.\n\n"
            "Спасибо, что выбираете BynexVPN 💙"
        ),
        reply_markup=start_keyboard(),
        parse_mode="HTML"
    )

# ================= RUN =================

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reply", reply))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CallbackQueryHandler(dialog_ok_callback, pattern="^dialog_ok:"))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_user_message))

    print("БОТ ЗАПУЩЕН")
    app.run_polling()
