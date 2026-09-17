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

# Piped API (YouTube proxy)
PIPED_INSTANCES = [
    'https://pipedapi.kavin.rocks',
    'https://piped-api.privacy.com.de',
    'https://api.piped.yt',
    'https://pipedapi.adminforge.de',
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
    # Ambil query dari args command
    query = ' '.join(context.args) if context.args else None
    
    # Kalau gak ada args, cek dari teks pesan langsung
    if not query and update.message and update.message.text:
        text = update.message.text
        # Handle /p atau /P dengan query
        for prefix in ['/p ', '/P ']:
            if text.startswith(prefix):
                query = text[len(prefix):].strip()
                break
        # Handle .p atau .P
        for prefix in ['.p ', '.P ']:
            if text.startswith(prefix):
                query = text[len(prefix):].strip()
                break

    if not query:
        await update.message.reply_text(
            "⚠️ **Lagu apa yang mau diputar?**\n\n"
            "Ketik: `/p judul lagu`\n"
            "Contoh: `/p sampai jumpa`",
            parse_mode='Markdown'
        )
        return

    loading = await update.message.reply_text(f"🔍 **Mencari:** {query}...")

    try:
        logger.info(f"Searching for: {query}")
        audio_path = await download_audio(query)
        
        if audio_path and os.path.exists(audio_path):
            file_size = os.path.getsize(audio_path)
            logger.info(f"Downloaded: {audio_path} ({file_size} bytes)")
            
            if file_size < 1000:  # File terlalu kecil, kemungkinan error
                os.remove(audio_path)
                await loading.edit_text("❌ **Gagal!** File tidak valid. Coba judul lain.")
                return
            
            with open(audio_path, 'rb') as f:
                await update.message.reply_audio(audio=f, title=query[:100])
            os.remove(audio_path)
            await loading.edit_text("✅ **Berhasil dikirim!** 🎵")
        else:
            logger.error(f"Download failed for: {query}")
            await loading.edit_text(
                "❌ **Gagal download!**\n\n"
                "Kemungkinan:\n"
                "• Lagu tidak ditemukan\n"
                "• Server sedang sibuk\n"
                "• Coba judul yang lebih spesifik"
            )
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await loading.edit_text("❌ **Error!** Coba lagi nanti.")


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pesan biasa yang diawali .p"""
    if update.message and update.message.text:
        text = update.message.text
        for prefix in ['.p ', '.P ']:
            if text.startswith(prefix):
                query = text[len(prefix):].strip()
                if query:
                    # Bikin fake context args
                    context.args = query.split()
                    await cmd_play(update, context)
                return


async def search_youtube(query: str):
    """Cari video di YouTube via Piped API"""
    async with httpx.AsyncClient(timeout=30) as client:
        for inst in PIPED_INSTANCES:
            try:
                logger.info(f"Trying Piped: {inst}")
                r = await client.get(
                    f"{inst}/search",
                    params={'q': query, 'filter': 'music_songs'}
                )
                if r.status_code == 200:
                    data = r.json()
                    if data and len(data) > 0:
                        v = data[0]
                        vid = v.get('url', '').split('v=')[-1]
                        title = v.get('title', 'Unknown')
                        logger.info(f"Found: {title} (ID: {vid})")
                        return {'id': vid, 'title': title}
                else:
                    logger.warning(f"Piped {inst} returned {r.status_code}")
            except Exception as e:
                logger.warning(f"Piped {inst} error: {e}")
                continue
    logger.error("All Piped instances failed!")
    return None


async def get_audio_url(video_id: str):
    """Dapetin URL audio stream"""
    async with httpx.AsyncClient(timeout=30) as client:
        for inst in PIPED_INSTANCES:
            try:
                logger.info(f"Getting streams from: {inst}")
                r = await client.get(f"{inst}/streams/{video_id}")
                if r.status_code == 200:
                    data = r.json()
                    streams = data.get('audioStreams', [])
                    if streams:
                        best = max(streams, key=lambda x: x.get('bitrate', 0))
                        url = best.get('url')
                        if url:
                            logger.info(f"Got audio URL (bitrate: {best.get('bitrate')})")
                            return url
                else:
                    logger.warning(f"Streams {inst} returned {r.status_code}")
            except Exception as e:
                logger.warning(f"Streams {inst} error: {e}")
                continue
    logger.error("Failed to get audio URL from all instances!")
    return None


async def download_audio(query: str):
    """Download audio dari YouTube"""
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        
        # Bersihin file lama
        for f in os.listdir(DOWNLOADS_DIR):
            fp = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)

        # Cari video
        video = await search_youtube(query)
        if not video:
            return None

        # Dapetin URL audio
        audio_url = await get_audio_url(video['id'])
        if not audio_url:
            return None

        # Download
        logger.info("Downloading audio...")
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(audio_url)
            if r.status_code == 200:
                ct = r.headers.get('content-type', '')
                ext = 'webm' if 'webm' in ct else 'm4a'
                path = os.path.join(DOWNLOADS_DIR, f"{video['id']}.{ext}")
                with open(path, 'wb') as f:
                    f.write(r.content)
                logger.info(f"Saved to: {path}")
                return path
            else:
                logger.error(f"Download failed: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        return None


# ========== TELEGRAM BOT ==========
async def run_bot():
    """Jalanin Telegram bot"""
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        logger.error("BOT_TOKEN belum diisi!")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers - /p DAN /P
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("p", cmd_play))
    app.add_handler(CommandHandler("P", cmd_play))  # Handle /P juga
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Telegram bot started!")

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

    await asyncio.Event().wait()


# ========== MAIN ==========
async def main():
    logger.info("Starting bot and web server...")
    await asyncio.gather(
        run_bot(),
        start_web_server()
    )


if __name__ == '__main__':
    asyncio.run(main())
