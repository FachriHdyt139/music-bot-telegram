import os
import logging
import asyncio
import subprocess
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
        for prefix in ['/p ', '/P ', '.p ', '.P ']:
            if text.startswith(prefix):
                query = text[len(prefix):].strip()
                break

    if not query:
        await update.message.reply_text(
            "⚠️ **Lagu apa yang mau diputar?**\n\n"
            "Ketik: `/p judul lagu`",
            parse_mode='Markdown'
        )
        return

    loading = await update.message.reply_text(f"🔍 **Mencari:** {query}...")

    try:
        logger.info(f"Searching: {query}")
        audio_path = await download_audio(query)

        if audio_path and os.path.exists(audio_path):
            file_size = os.path.getsize(audio_path)
            logger.info(f"Downloaded: {file_size} bytes")

            if file_size < 1000:
                os.remove(audio_path)
                await loading.edit_text("❌ **Gagal!** Coba judul lain.")
                return

            with open(audio_path, 'rb') as f:
                await update.message.reply_audio(audio=f, title=query[:100])
            os.remove(audio_path)
            await loading.edit_text("✅ **Berhasil!** 🎵")
        else:
            await loading.edit_text("❌ **Gagal download!** Coba judul lain.")
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


# ========== DOWNLOAD DARI YOUTUBE ==========
async def download_audio(query: str):
    """Download audio dari YouTube pakai yt-dlp"""
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

        # Bersihin file lama
        for f in os.listdir(DOWNLOADS_DIR):
            fp = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)

        # Command yt-dlp
        cmd = [
            'yt-dlp',
            '-f', '140',  # format m4a audio only
            '--extractor-args', 'youtube:player_client=visionos',
            '--no-playlist',
            '--no-warnings',
            '--no-overwrites',
            '-o', f'{DOWNLOADS_DIR}/%(id)s.%(ext)s',
            f'ytsearch1:{query}'
        ]

        logger.info(f"Running: {' '.join(cmd)}")

        # Jalankan subprocess
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"yt-dlp error: {stderr.decode()}")
            return None

        logger.info(f"yt-dlp output: {stdout.decode()}")

        # Cari file yang terdownload
        files = os.listdir(DOWNLOADS_DIR)
        if files:
            mp3_files = [f for f in files if f.endswith(('.mp3', '.m4a', '.webm', '.opus'))]
            if mp3_files:
                latest = max(
                    [os.path.join(DOWNLOADS_DIR, f) for f in mp3_files],
                    key=os.path.getmtime
                )
                return latest

        return None

    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        return None


# ========== TELEGRAM BOT ==========
async def run_bot():
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        logger.error("BOT_TOKEN belum diisi!")
        return

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
    return web.json_response({"status": "ok", "bot": "running"})


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
    logger.info(f"✅ Web server started on port {PORT}")

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
