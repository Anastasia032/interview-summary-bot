import os
import logging
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Змінні середовища
BOT_TOKEN = os.environ.get("8290920751:AAGgDL9XTWj0MaDqSeWgWY7aoIaVor9tKiU")
PEOPLEFORCE_API_KEY = os.environ.get("LmLhye6ifyMyDWPzFH7UopUTeDgPw7rYXYE1P7yNxR4A4keNRyj5")
RECRUITER_CHAT_ID = int(os.environ.get("-1003689121115"))
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "secret123")
PORT = int(os.environ.get("PORT", 8080))

# Стани розмови
WAITING_FEEDBACK = 1
WAITING_CANDIDATE_ID = 2

# Тимчасове сховище
pending_summaries = {}

# ==================== ОТРИМАННЯ SUMMARY ВІД APPS SCRIPT ====================
async def receive_summary(request):
    try:
        secret = request.headers.get("X-Secret")
        if secret != WEBHOOK_SECRET:
            return web.Response(status=403, text="Forbidden")

        data = await request.json()
        summary = data.get("summary")
        file_name = data.get("file_name", "невідомий файл")

        if not summary:
            return web.Response(status=400, text="No summary")

        # Зберігаємо summary тимчасово
        summary_id = str(hash(summary))[:8]
        pending_summaries[summary_id] = {
            "summary": summary,
            "file_name": file_name,
            "candidate_id": None,
            "feedback": None
        }

        # Надсилаємо в Telegram з кнопкою
        app = request.app["bot_app"]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Додати фідбек", callback_data=f"feedback:{summary_id}")],
            [InlineKeyboardButton("📋 Додати в PeopleForce", callback_data=f"peopleforce:{summary_id}")]
        ])

        text = f"🎯 Summary співбесіди\n📄 {file_name}\n\n{summary}"

        # Якщо текст довгий — ділимо на частини
        if len(text) > 4000:
            await app.bot.send_message(
                chat_id=RECRUITER_CHAT_ID,
                text=text[:4000]
            )
            await app.bot.send_message(
                chat_id=RECRUITER_CHAT_ID,
                text=text[4000:],
                reply_markup=keyboard
            )
        else:
            await app.bot.send_message(
                chat_id=RECRUITER_CHAT_ID,
                text=text,
                reply_markup=keyboard
            )

        return web.Response(text="OK")

    except Exception as e:
        logger.error(f"Помилка receive_summary: {e}")
        return web.Response(status=500, text=str(e))


# ==================== КНОПКА "ДОДАТИ ФІДБЕК" ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("feedback:"):
        summary_id = data.split(":")[1]
        context.user_data["summary_id"] = summary_id
        await query.message.reply_text(
            "✍️ Напиши свій короткий фідбек по кандидату:"
        )
        return WAITING_FEEDBACK

    if data.startswith("peopleforce:"):
        summary_id = data.split(":")[1]
        context.user_data["summary_id"] = summary_id
        await query.message.reply_text(
            "🔍 Введи ID кандидата з PeopleForce:"
        )
        return WAITING_CANDIDATE_ID


# ==================== ОТРИМАННЯ ФІДБЕКУ ====================
async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedback = update.message.text
    summary_id = context.user_data.get("summary_id")

    if not summary_id or summary_id not in pending_summaries:
        await update.message.reply_text("❌ Сесія застаріла, спробуй знову.")
        return ConversationHandler.END

    pending_summaries[summary_id]["feedback"] = feedback

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Додати в PeopleForce", callback_data=f"peopleforce:{summary_id}")]
    ])

    await update.message.reply_text(
        f"✅ Фідбек збережено!\n\n_{feedback}_\n\nТепер можеш додати все в PeopleForce:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ==================== ОТРИМАННЯ CANDIDATE ID ====================
async def receive_candidate_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    candidate_id = update.message.text.strip()
    summary_id = context.user_data.get("summary_id")

    if not summary_id or summary_id not in pending_summaries:
        await update.message.reply_text("❌ Сесія застаріла, спробуй знову.")
        return ConversationHandler.END

    data = pending_summaries[summary_id]
    summary = data["summary"]
    feedback = data.get("feedback", "")

    note = summary
    if feedback:
        note += f"\n\n---\nФІДБЕК РЕКРУТЕРА:\n{feedback}"

    success = await add_note_to_peopleforce(candidate_id, note)

    if success:
        await update.message.reply_text(f"✅ Нотатку додано в PeopleForce для кандидата #{candidate_id}")
        del pending_summaries[summary_id]
    else:
        await update.message.reply_text("❌ Помилка при додаванні в PeopleForce. Перевір ID кандидата.")

    return ConversationHandler.END


# ==================== PEOPLEFORCE API ====================
async def add_note_to_peopleforce(candidate_id: str, note: str):
    import aiohttp
    url
