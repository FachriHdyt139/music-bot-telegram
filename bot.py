import os
import logging
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
RENDER_URL = os.getenv('RENDER_EXTERNAL_URL', '')
PORT = int(os.getenv('PORT', '8080'))
DOWNLOADS_DIR = 'downloads'

# Piped API instances
PIPED_INSTANCES = [
    'https://pipedapi.kavin.rocks',
    'https://piped-api.privacy.com.de',
    'https://api.piped.yt',
]


# ========== BOT HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "🎵 **Halo! Gue Music Bot!** 🎵\n\n"
        "Cara pake gue gampang banget:\n"
        "Ketik: `/p judul lagu`\n\n"
        "**Contoh:**\n"
        "• `/p sampai jumpa`\n"
        "• `/p dj tiktok viral 2024`\n\n"
        "Gue bakal cariin lagunya terus kirim file mp3-nya! 🎧"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')


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
        await update.message.reply_text(
            "⚠️ **Lagu apa yang mau diputar?**\nKetik: `/p judul lagu`",
            parse_mode='Markdown'
        )
        return

    if not query:
        return

    loading_msg = await update.message.reply_text(
        f"🔍 **Mencari:** {query}... ⏳",
        parse_mode='Markdown'
    )

    try:
        audio_path = await download_audio(query)

        if audio_path and os.path.exists(audio_path):
            file_size = os.path.getsize(audio_path)
            if file_size > 50 * 1024 * 1024:
                await loading_msg.edit_text("❌ **File terlalu besar!** Coba judul lain.", parse_mode='Markdown')
                os.remove(audio_path)
                return

            with open(audio_path, 'rb') as audio:
                await update.message.reply_audio(
                    audio=audio,
                    title=query[:100],
                    performer="YouTube Audio"
                )

            os.remove(audio_path)
            await loading_msg.edit_text("✅ **Berhasil!** 🎉", parse_mode='Markdown')
        else:
            await loading_msg.edit_text("❌ **Gagal download!** Coba judul lain.", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error: {e}")
        await loading_msg.edit_text("❌ **Error!** Coba lagi nanti.", parse_mode='Markdown')


async def search_youtube(query: str):
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
                        video_id = video_url.split('v=')[-1] if 'v=' in video_url else video_url
                        return {'id': video_id, 'title': video.get('title', 'Unknown')}
            except Exception as e:
                logger.warning(f"Piped {instance} failed: {e}")
                continue
    return None


async def get_audio_url(video_id: str):
    async with httpx.AsyncClient(timeout=30) as client:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    streams = data.get('audioStreams', [])
                    if streams:
                        best = max(streams, key=lambda x: x.get('bitrate', 0))
                        return best.get('url')
            except Exception as e:
                logger.warning(f"Piped {instance} failed: {e}")
                continue
    return None


async def download_audio(query: str):
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

        for f in os.listdir(DOWNLOADS_DIR):
            fp = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)

        video = await search_youtube(query)
        if not video:
            return None

        audio_url = await get_audio_url(video['id'])
        if not audio_url:
            return None

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(audio_url)
            if response.status_code == 200:
                ct = response.headers.get('content-type', '')
                ext = 'webm' if 'webm' in ct else 'm4a'
                file_path = os.path.join(DOWNLOADS_DIR, f"{video['id']}.{ext}")
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                return file_path
        return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None


# ========== WEB SERVER ==========
async def handle_webhook(request):
    """Handle webhook updates dari Telegram"""
    app = request.app
    bot_app = app['bot_app']
    
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return web.Response(text='OK')
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(text='ERROR', status=500)


async def health_check(request):
    return web.json_response({"status": "ok"})


async def on_startup(app):
    """Setup webhook saat server mulai"""
    bot_app = app['bot_app']
    
    # Set webhook ke Telegram
    webhook_url = f"{RENDER_URL}/webhook"
    await bot_app.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to: {webhook_url}")


async def on_cleanup(app):
    """Cleanup saat server stop"""
    bot_app = app['bot_app']
    await bot_app.bot.delete_webhook()
    await bot_app.shutdown()


def main():
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        print("❌ ERROR: Token bot belum diisi!")
        return

    if not RENDER_URL:
        print("❌ ERROR: RENDER_EXTERNAL_URL belum diisi!")
        print("Pastikan service di-set ke Web Service di Render!")
        return

    # Build bot application
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("p", search_and_send))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_send))

    # Build web server
    web_app = web.Application()
    web_app['bot_app'] = bot_app
    web_app.router.add_post('/webhook', handle_webhook)
    web_app.router.add_get('/', health_check)
    web_app.router.add_get('/health', health_check)
    web_app.on_startup.append(on_startup)
    web_app.on_cleanup.append(on_cleanup)

    print("🤖 Bot Musik Mulai Jalan! 🎵")
    print(f"Webhook: {RENDER_URL}/webhook")
    print(f"Health: {RENDER_URL}/")

    # Jalankan web server (ini juga handle bot via webhook)
    web.run_app(web_app, host='0.0.0.0', port=PORT)


if __name__ == '__main__':
    main()
