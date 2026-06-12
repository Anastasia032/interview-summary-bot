import os
import logging
import asyncio
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
import aiohttp as aiohttp_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PEOPLEFORCE_API_KEY = os.environ.get("PEOPLEFORCE_API_KEY")
RECRUITER_CHAT_ID = int(os.environ.get("RECRUITER_CHAT_ID", "0"))
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "secret123")
PORT = int(os.environ.get("PORT", 8080))

WAITING_FEEDBACK = 1
WAITING_CANDIDATE_ID = 2

pending_summaries = {}

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

        summary_id = str(abs(hash(summary)))[:8]
        pending_summaries[summary_id] = {
            "summary": summary,
            "file_name": file_name,
            "feedback": None
        }

        app = request.app["bot_app"]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Додати фідбек", callback_data=f"feedback:{summary_id}")],
            [InlineKeyboardButton("📋 Додати в PeopleForce", callback_data=f"peopleforce:{summary_id}")]
        ])

        text = f"🎯 Summary співбесіди\n📄 {file_name}\n\n{summary}"

        if len(text) > 4000:
            await app.bot.send_message(chat_id=RECRUITER_CHAT_ID, text=text[:4000])
            await app.bot.send_message(chat_id=RECRUITER_CHAT_ID, text=text[4000:], reply_markup=keyboard)
        else:
            await app.bot.send_message(chat_id=RECRUITER_CHAT_ID, text=text, reply_markup=keyboard)

        return web.Response(text="OK")

    except Exception as e:
        logger.error(f"Помилка receive_summary: {e}")
        return web.Response(status=500, text=str(e))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("feedback:"):
        summary_id = data.split(":")[1]
        context.user_data["summary_id"] = summary_id
        await query.message.reply_text("✍️ Напиши свій короткий фідбек по кандидату:")
        return WAITING_FEEDBACK

    if data.startswith("peopleforce:"):
        summary_id = data.split(":")[1]
        context.user_data["summary_id"] = summary_id
        await query.message.reply_text("🔍 Введи ID кандидата з PeopleForce:")
        return WAITING_CANDIDATE_ID


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
        f"✅ Фідбек збережено!\n\n{feedback}\n\nТепер можеш додати все в PeopleForce:",
        reply_markup=keyboard
    )
    return ConversationHandler.END


async def receive_candidate_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    candidate_id = update.message.text.strip()
    summary_id = context.user_data.get("summary_id")

    if not summary_id or summary_id not in pending_summaries:
        await update.message.reply_text("❌ Сесія застаріла, спробуй знову.")
        return ConversationHandler.END

    data = pending_summaries[summary_id]
    note = data["summary"]
    if data.get("feedback"):
        note += f"\n\n---\nФІДБЕК РЕКРУТЕРА:\n{data['feedback']}"

    success = await add_note_to_peopleforce(candidate_id, note)

    if success:
        await update.message.reply_text(f"✅ Нотатку додано в PeopleForce для кандидата #{candidate_id}")
        del pending_summaries[summary_id]
    else:
        await update.message.reply_text("❌ Помилка. Перевір ID кандидата.")

    return ConversationHandler.END


async def add_note_to_peopleforce(candidate_id: str, note: str):
    try:
        url = f"https://app.peopleforce.io/api/public/v3/recruitment/candidates/{candidate_id}/notes"
        headers = {
            "X-API-KEY": PEOPLEFORCE_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {"comment": note}

        async with aiohttp_client.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    logger.info("PeopleForce: нотатку додано")
                    return True
                else:
                    text = await resp.text()
                    logger.error(f"PeopleForce помилка {resp.status}: {text}")
                    return False
    except Exception as e:
        logger.error(f"Помилка PeopleForce: {e}")
        return False


async def main():
    app_bot = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            WAITING_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)],
            WAITING_CANDIDATE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_candidate_id)],
        },
        fallbacks=[]
    )
    app_bot.add_handler(conv_handler)

    await app_bot.initialize()
    await app_bot.start()

    web_app = web.Application()
    web_app["bot_app"] = app_bot
    web_app.router.add_post("/summary", receive_summary)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logger.info(f"Бот запущено на порту {PORT}")

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
