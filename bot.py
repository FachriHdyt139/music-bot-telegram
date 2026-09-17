import os
import logging
import asyncio
import base64
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
YOUTUBE_COOKIES = os.getenv('YOUTUBE_COOKIES', '')
DOWNLOADS_DIR = 'downloads'


# ========== BOT HANDLERS ==========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 **Music Bot Ready!**\n\n"
        "Ketik: `/p judul lagu`\n"
        "Contoh: `/p sampai jumpa`\n\n"
        "Full durasi! 🎧",
        parse_mode='Markdown'
    )


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args) if context.args else None

    if not query and update.message and update.message.text:
        text = update.message.text
        for prefix in ['/p ', '/P ', '.p ', '.P ']:
            if text.startswith(prefix):
                query = text[len(prefix):].strip()
                break

    if not query:
        await update.message.reply_text("⚠️ **Ketik: `/p judul lagu`**", parse_mode='Markdown')
        return

    loading = await update.message.reply_text(f"🔍 **Mencari:** {query}...")

    try:
        logger.info(f"Search: {query}")

        # Coba YouTube dulu (full durasi)
        result = await download_from_youtube(query)

        # Kalau YouTube gagal, fallback ke Deezer (30 detik)
        if not result:
            logger.info("YouTube failed, trying Deezer...")
            result = await download_from_deezer(query)

        if result:
            audio_path, title, artist = result
            if os.path.exists(audio_path):
                file_size = os.path.getsize(audio_path)
                logger.info(f"Downloaded: {file_size} bytes")

                if file_size < 1000:
                    os.remove(audio_path)
                    await loading.edit_text("❌ **Gagal!** Coba judul lain.")
                    return

                with open(audio_path, 'rb') as audio:
                    await update.message.reply_audio(
                        audio=audio,
                        title=title[:100],
                        performer=artist or "Unknown"
                    )
                os.remove(audio_path)
                await loading.edit_text(f"✅ **{title}** - {artist}")
            else:
                await loading.edit_text("❌ **Gagal download!** Coba judul lain.")
        else:
            await loading.edit_text("❌ **Lagu tidak ditemukan!** Coba judul lain.")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await loading.edit_text("❌ **Error!** Coba lagi.")


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        text = update.message.text
        for prefix in ['.p ', '.P ']:
            if text.startswith(prefix):
                query = text[len(prefix):].strip()
                if query:
                    context.args = query.split()
                    await cmd_play(update, context)
                return


# ========== YOUTUBE (FULL DURASI) ==========
def setup_cookies_file():
    """Setup cookies file dari environment variable"""
    if not YOUTUBE_COOKIES:
        return None

    cookies_path = os.path.join(DOWNLOADS_DIR, 'cookies.txt')
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    try:
        decoded = base64.b64decode(YOUTUBE_COOKIES).decode('utf-8')
        with open(cookies_path, 'w') as f:
            f.write(decoded)
        logger.info("Cookies loaded from base64")
    except Exception:
        with open(cookies_path, 'w') as f:
            f.write(YOUTUBE_COOKIES)
        logger.info("Cookies loaded directly")

    return cookies_path


async def download_from_youtube(query: str):
    """Download audio dari YouTube pakai yt-dlp + cookies + node runtime"""
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

        for f in os.listdir(DOWNLOADS_DIR):
            fp = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(fp) and not f.endswith('.txt'):
                os.remove(fp)

        cookies_path = setup_cookies_file()

        if not cookies_path or not os.path.exists(cookies_path):
            logger.error("No cookies available!")
            return None

        # Step 1: Search untuk dapat video ID
        search_cmd = [
            'yt-dlp',
            '--js-runtimes', 'node',
            '--cookies', cookies_path,
            '--extractor-args', 'youtube:player_client=web',
            '--flat-playlist',
            '--print', '%(id)s|||%(title)s',
            f'ytsearch1:{query}'
        ]

        logger.info("Searching YouTube...")
        process = await asyncio.create_subprocess_exec(
            *search_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"Search error: {stderr.decode()}")
            return None

        output = stdout.decode().strip()
        if not output:
            logger.error("No search results")
            return None

        # Parse video ID dan title
        parts = output.split('|||')
        video_id = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else query

        logger.info(f"Found: {title} (ID: {video_id})")

        # Step 2: Download audio
        download_cmd = [
            'yt-dlp',
            '--js-runtimes', 'node',
            '--cookies', cookies_path,
            '--extractor-args', 'youtube:player_client=web',
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '5',
            '--no-playlist',
            '--no-warnings',
            '--no-overwrites',
            '-o', f'{DOWNLOADS_DIR}/%(id)s.%(ext)s',
            f'https://www.youtube.com/watch?v={video_id}'
        ]

        logger.info("Downloading audio...")
        process = await asyncio.create_subprocess_exec(
            *download_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"Download error: {stderr.decode()}")
            return None

        logger.info("Download success!")

        # Cari file yang terdownload
        files = os.listdir(DOWNLOADS_DIR)
        audio_files = [f for f in files if f.endswith(('.mp3', '.m4a', '.webm', '.opus'))]
        if audio_files:
            latest = max(
                [os.path.join(DOWNLOADS_DIR, f) for f in audio_files],
                key=os.path.getmtime
            )
            return (latest, title, "YouTube")

        return None

    except Exception as e:
        logger.error(f"YouTube error: {e}", exc_info=True)
        return None


# ========== DEEZER (FALLBACK) ==========
async def download_from_deezer(query: str):
    """Download preview dari Deezer (fallback, 30 detik)"""
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

        async with httpx.AsyncClient(timeout=15) as client:
            url = f"https://api.deezer.com/search?q={query}&limit=1"
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                results = data.get('data', [])
                if results:
                    track = results[0]
                    title = track.get('title', 'Unknown')
                    artist = track.get('artist', {}).get('name', 'Unknown')
                    preview_url = track.get('preview', '')

                    if preview_url:
                        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as dl_client:
                            r = await dl_client.get(preview_url)
                            if r.status_code == 200:
                                file_path = os.path.join(DOWNLOADS_DIR, f"{track.get('id')}.mp3")
                                with open(file_path, 'wb') as f:
                                    f.write(r.content)
                                return (file_path, f"{title} (Preview 30s)", artist)
        return None
    except Exception as e:
        logger.error(f"Deezer error: {e}")
        return None


# ========== TELEGRAM BOT ==========
async def run_bot():
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        logger.error("BOT_TOKEN belum diisi!")
        return

    if YOUTUBE_COOKIES:
        logger.info("✅ YouTube cookies available!")
    else:
        logger.warning("⚠️ No YouTube cookies! Will use Deezer fallback.")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("p", cmd_play))
    app.add_handler(CommandHandler("P", cmd_play))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Bot started!")

    await asyncio.Event().wait()


# ========== WEB SERVER ==========
async def handle_index(request):
    has_cookies = bool(YOUTUBE_COOKIES)
    return web.json_response({
        "status": "ok",
        "bot": "running",
        "youtube_cookies": "set" if has_cookies else "not set"
    })


async def handle_health(request):
    return web.json_response({"status": "healthy"})


async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/healthcheck', handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Web server on port {PORT}")

    await asyncio.Event().wait()


# ========== MAIN ==========
async def main():
    logger.info("Starting...")
    await asyncio.gather(
        run_bot(),
        start_web_server()
    )


if __name__ == '__main__':
    asyncio.run(main())
