import os
import logging
import asyncio
import threading
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

# Token bot dari BotFather
BOT_TOKEN = os.getenv('BOT_TOKEN', 'TOKEN_LO_DISINI')

# Folder buat temporary storage
DOWNLOADS_DIR = 'downloads'

# Piped API instances (YouTube proxy gratis)
PIPED_INSTANCES = [
    'https://pipedapi.kavin.rocks',
    'https://piped-api.privacy.com.de',
    'https://api.piped.yt',
]


# ========== WEB SERVER (Health Check buat Render) ==========
async def health_check(request):
    """Health check endpoint buat Render"""
    return web.json_response({"status": "ok", "bot": "running"})


async def start_web_server():
    """Jalanin web server di background buat health check"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("Web server started on port 8080")
    
    # Biarkan server jalan terus
    while True:
        await asyncio.sleep(3600)


# ========== TELEGRAM BOT HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler buat command /start"""
    welcome_msg = (
        "🎵 **Halo! Gue Music Bot!** 🎵\n\n"
        "Cara pake gue gampang banget:\n"
        "Ketik: `/p judul lagu`\n\n"
        "**Contoh:**\n"
        "• `/p sampai jumpa`\n"
        "• `/p dj tiktok viral 2024`\n"
        "• `/p dangdut koplo terbaru`\n\n"
        "Gue bakal cariin lagunya terus kirim file mp3-nya! 🎧\n\n"
        "**Command Lain:**\n"
        "• `/start` - Tampilkan pesan ini"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')


async def search_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler buat command /p judul lagu atau pesan .p"""
    if context.args:
        query = ' '.join(context.args)
    elif update.message and update.message.text:
        text = update.message.text
        if text.lower().startswith('.p '):
            query = text[3:].strip()
        else:
            return
    else:
        await update.message.reply_text(
            "⚠️ **Lagu apa yang mau diputar?**\n\n"
            "Ketik: `/p judul lagu`\n"
            "Contoh: `/p sampai jumpa`\n",
            parse_mode='Markdown'
        )
        return

    if not query:
        await update.message.reply_text(
            "⚠️ **Lagu apa yang mau diputar?**\n\n"
            "Ketik: `/p judul lagu`\n",
            parse_mode='Markdown'
        )
        return

    loading_msg = await update.message.reply_text(
        f"🔍 **Mencari:** {query}... ⏳\n"
        "Sabar ya, gue download dulu!",
        parse_mode='Markdown'
    )

    try:
        audio_path = await download_audio(query)

        if audio_path and os.path.exists(audio_path):
            file_size = os.path.getsize(audio_path)
            if file_size > 50 * 1024 * 1024:
                await loading_msg.edit_text(
                    "❌ **File terlalu besar!** ( > 50MB)\n"
                    "Coba judul lagu yang lain.",
                    parse_mode='Markdown'
                )
                os.remove(audio_path)
                return

            with open(audio_path, 'rb') as audio:
                await update.message.reply_audio(
                    audio=audio,
                    title=query[:100],
                    performer="YouTube Audio"
                )

            os.remove(audio_path)
            await loading_msg.edit_text("✅ **Lagu berhasil dikirim!** 🎉", parse_mode='Markdown')
        else:
            await loading_msg.edit_text(
                "❌ **Gagal download lagu!**\n"
                "Coba judul lain atau cek ejaan.",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error: {e}")
        await loading_msg.edit_text(
            "❌ **Error bos!**\n"
            "Coba lagi nanti ya.",
            parse_mode='Markdown'
        )


async def search_youtube(query: str):
    """Cari video di YouTube via Piped API"""
    async with httpx.AsyncClient(timeout=30) as client:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/search"
                params = {'q': query, 'filter': 'music_songs'}
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if data and len(data) > 0:
                        video = data[0]
                        video_url = video.get('url', '')
                        video_id = video_url.replace('/watch?v=', '') if 'v=' in video_url else video.get('url', '')
                        return {
                            'id': video_id,
                            'title': video.get('title', 'Unknown'),
                            'duration': video.get('duration', 0)
                        }
            except Exception as e:
                logger.warning(f"Piped instance {instance} failed: {e}")
                continue
    return None


async def get_audio_url(video_id: str):
    """Dapatkan URL audio stream dari video YouTube via Piped API"""
    async with httpx.AsyncClient(timeout=30) as client:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    audio_streams = data.get('audioStreams', [])
                    if audio_streams:
                        best_stream = max(audio_streams, key=lambda x: x.get('bitrate', 0))
                        return best_stream.get('url')
            except Exception as e:
                logger.warning(f"Piped instance {instance} failed: {e}")
                continue
    return None


async def download_audio(query: str):
    """Download audio dari YouTube via Piped API"""
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

        for f in os.listdir(DOWNLOADS_DIR):
            file_path = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(file_path):
                os.remove(file_path)

        logger.info(f"Searching for: {query}")
        video = await search_youtube(query)
        if not video:
            logger.error("No video found")
            return None

        logger.info(f"Found video: {video['title']} (ID: {video['id']})")

        audio_url = await get_audio_url(video['id'])
        if not audio_url:
            logger.error("Failed to get audio URL")
            return None

        logger.info("Downloading audio...")

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(audio_url)
            if response.status_code == 200:
                ext = 'm4a'
                content_type = response.headers.get('content-type', '')
                if 'webm' in content_type:
                    ext = 'webm'
                elif 'mp4' in content_type:
                    ext = 'm4a'

                file_path = os.path.join(DOWNLOADS_DIR, f"{video['id']}.{ext}")
                with open(file_path, 'wb') as f:
                    f.write(response.content)

                logger.info(f"Download complete: {file_path}")
                return file_path
            else:
                logger.error(f"Download failed with status: {response.status_code}")
                return None

    except Exception as e:
        logger.error(f"Download error: {e}")
        return None


# ========== MAIN ==========
async def main():
    """Fungsi utama - jalanin bot + web server bareng"""
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        print("❌ ERROR: Token bot belum diisi!")
        print("Silakan isi token di environment variable BOT_TOKEN")
        return

    # Bikin application
    app = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("p", search_and_send))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_send))

    # Initialize application
    await app.initialize()

    # Start web server di background task
    asyncio.create_task(start_web_server())

    # Start polling
    print("🤖 Bot Musik Mulai Jalan! 🎵")
    print("Web server di port 8080")
    await app.start()
    await app.updater.start_polling()

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
