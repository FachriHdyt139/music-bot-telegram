import os
import logging
import asyncio
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv('BOT_TOKEN', 'TOKEN_LO_DISINI')
PORT = int(os.getenv('PORT', '8080'))
DOWNLOADS_DIR = 'downloads'

# Piped API
PIPED_INSTANCES = [
    'https://pipedapi.kavin.rocks',
    'https://piped-api.privacy.com.de',
    'https://api.piped.yt',
]

# Global bot app
telegram_app: Application = None


# ========== HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 **Music Bot Ready!** 🎵\n\n"
        "Ketik: `/p judul lagu`\n"
        "Contoh: `/p sampai jumpa`",
        parse_mode='Markdown'
    )


async def search_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        query = ' '.join(context.args)
    elif update.message and update.message.text:
        text = update.message.text
        if text.lower().startswith('.p '):
            query = text[3:].strip()
        else:
            return
    else:
        return

    if not query:
        return

    loading = await update.message.reply_text(f"🔍 Mencari: {query}...")

    try:
        audio_path = await download_audio(query)
        if audio_path and os.path.exists(audio_path):
            with open(audio_path, 'rb') as f:
                await update.message.reply_audio(audio=f, title=query[:100])
            os.remove(audio_path)
            await loading.edit_text("✅ Berhasil!")
        else:
            await loading.edit_text("❌ Gagal! Coba judul lain.")
    except Exception as e:
        logger.error(f"Error: {e}")
        await loading.edit_text("❌ Error!")


async def search_youtube(query: str):
    async with httpx.AsyncClient(timeout=30) as client:
        for inst in PIPED_INSTANCES:
            try:
                r = await client.get(f"{inst}/search", params={'q': query, 'filter': 'music_songs'})
                if r.status_code == 200:
                    data = r.json()
                    if data:
                        v = data[0]
                        vid = v.get('url', '').split('v=')[-1]
                        return {'id': vid, 'title': v.get('title', '')}
            except:
                continue
    return None


async def get_audio_url(video_id: str):
    async with httpx.AsyncClient(timeout=30) as client:
        for inst in PIPED_INSTANCES:
            try:
                r = await client.get(f"{inst}/streams/{video_id}")
                if r.status_code == 200:
                    streams = r.json().get('audioStreams', [])
                    if streams:
                        return max(streams, key=lambda x: x.get('bitrate', 0)).get('url')
            except:
                continue
    return None


async def download_audio(query: str):
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        for f in os.listdir(DOWNLOADS_DIR):
            os.remove(os.path.join(DOWNLOADS_DIR, f))

        video = await search_youtube(query)
        if not video:
            return None

        audio_url = await get_audio_url(video['id'])
        if not audio_url:
            return None

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(audio_url)
            if r.status_code == 200:
                ct = r.headers.get('content-type', '')
                ext = 'webm' if 'webm' in ct else 'm4a'
                path = os.path.join(DOWNLOADS_DIR, f"{video['id']}.{ext}")
                with open(path, 'wb') as f:
                    f.write(r.content)
                return path
        return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None


# ========== FASTAPI ==========
@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        logger.error("BOT_TOKEN belum diisi!")
        yield
        return

    # Build & init bot
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("p", search_and_send))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_send))
    
    await telegram_app.initialize()
    await telegram_app.start()
    
    # Start polling
    await telegram_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot started with polling!")
    
    yield
    
    # Shutdown
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()


fastapi_app = FastAPI(lifespan=lifespan)


@fastapi_app.get("/")
async def root():
    return {"status": "ok"}


@fastapi_app.get("/healthcheck")
async def healthcheck():
    return {"status": "healthy"}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(fastapi_app, host='0.0.0.0', port=PORT)
