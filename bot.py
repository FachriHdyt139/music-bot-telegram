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
            "⚠️ **Ketik: `/p judul lagu`**",
            parse_mode='Markdown'
        )
        return

    loading = await update.message.reply_text(f"🔍 **Mencari:** {query}...")

    try:
        logger.info(f"Search: {query}")
        result = await search_and_download(query)

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
                    caption = f"🎵 {title}"
                    if artist:
                        caption += f"\n👤 {artist}"
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


# ========== DEEZER API ==========
async def search_deezer(query: str):
    """Cari lagu di Deezer API (gratis, gak perlu API key)"""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            url = f"https://api.deezer.com/search?q={query}&limit=5"
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                results = data.get('data', [])
                if results:
                    return results
        except Exception as e:
            logger.error(f"Deezer search error: {e}")
    return None


async def search_and_download(query: str):
    """Cari & download audio dari Deezer"""
    try:
        os.makedirs('downloads', exist_ok=True)

        # Bersihin file lama
        for f in os.listdir('downloads'):
            fp = os.path.join('downloads', f)
            if os.path.isfile(fp):
                os.remove(fp)

        # Cari di Deezer
        results = await search_deezer(query)
        if not results:
            return None

        # Ambil yang paling cocok
        track = results[0]
        title = track.get('title', 'Unknown')
        artist = track.get('artist', {}).get('name', 'Unknown')
        preview_url = track.get('preview', '')

        if not preview_url:
            logger.error("No preview URL found")
            return None

        logger.info(f"Found: {title} - {artist}")
        logger.info(f"Preview URL: {preview_url[:80]}...")

        # Download preview (30 detik)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(preview_url)
            if r.status_code == 200:
                file_path = os.path.join('downloads', f"{track.get('id')}.mp3")
                with open(file_path, 'wb') as f:
                    f.write(r.content)
                logger.info(f"Saved: {file_path}")
                return (file_path, title, artist)
            else:
                logger.error(f"Download failed: {r.status_code}")

        return None

    except Exception as e:
        logger.error(f"Search/download error: {e}", exc_info=True)
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
