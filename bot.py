import os
import logging
import asyncio
import httpx
from aiohttp import web
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


# ========== BOT HANDLERS ==========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 **Music Bot Ready!**\n\n"
        "Ketik: `/p judul lagu`\n"
        "Contoh: `/p sampai jumpa`",
        parse_mode='Markdown'
    )


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args) if context.args else None
    
    if not query and update.message and update.message.text:
        text = update.message.text
        if text.lower().startswith('.p '):
            query = text[3:].strip()

    if not query:
        await update.message.reply_text("⚠️ Ketik: `/p judul lagu`", parse_mode='Markdown')
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


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        text = update.message.text
        if text.lower().startswith('.p '):
            query = text[3:].strip()
            if query:
                await cmd_play(update, context)


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


# ========== TELEGRAM BOT RUNNER ==========
async def run_bot():
    """Jalanin Telegram bot"""
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        logger.error("BOT_TOKEN belum diisi!")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("p", cmd_play))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Telegram bot started!")

    # Keep running
    await asyncio.Event().wait()


# ========== WEB SERVER ==========
async def handle_index(request):
    return web.json_response({"status": "ok", "bot": "running"})


async def handle_health(request):
    return web.json_response({"status": "healthy"})


async def start_web_server():
    """Jalanin web server buat health check"""
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/healthcheck', handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Web server started on port {PORT}")

    # Keep running
    await asyncio.Event().wait()


# ========== MAIN ==========
async def main():
    """Jalanin bot + web server bareng"""
    logger.info("Starting bot and web server...")
    
    # Run both concurrently
    await asyncio.gather(
        run_bot(),
        start_web_server()
    )


if __name__ == '__main__':
    asyncio.run(main())
