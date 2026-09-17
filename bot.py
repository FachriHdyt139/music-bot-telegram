import os
import logging
import asyncio
import httpx
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN', 'TOKEN_LO_DISINI')
PORT = int(os.getenv('PORT', '8080'))
RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY', '2be0c6b79emsh877b9588fd0d1a9p1f7a12jsnec208cb78e35')
DOWNLOADS_DIR = 'downloads'


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 **Music Bot Ready!**\n\n"
        "Ketik: `/p judul lagu`\n"
        "Contoh: `/p sampai jumpa`\n\n"
        "Full durasi dari YouTube! 🎧",
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

        video_id, title = await search_youtube(query)
        if not video_id:
            await loading.edit_text("❌ **Lagu tidak ditemukan!** Coba judul lain.")
            return

        logger.info(f"Found: {title} (ID: {video_id})")
        await loading.edit_text(f"📥 **Download:** {title}...")

        result = await download_via_rapidapi(video_id, title)
        if result:
            audio_path, song_title = result
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                with open(audio_path, 'rb') as audio:
                    await update.message.reply_audio(
                        audio=audio,
                        title=song_title[:100],
                        performer="YouTube"
                    )
                os.remove(audio_path)
                await loading.edit_text(f"✅ **{song_title}**")
            else:
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                await loading.edit_text("❌ **Gagal download!** Coba judul lain.")
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


async def search_youtube(query: str):
    """Search YouTube via Invidious API, return (video_id, title)"""
    instances = [
        "https://inv.nadeko.net",
        "https://invidious.protokolla.fi",
        "https://invidious.privacyredirect.com",
        "https://vid.puffyan.us",
        "https://yt.artemislena.eu",
    ]

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for instance in instances:
            try:
                url = f"{instance}/api/v1/search"
                r = await client.get(url, params={"q": query, "type": "video", "sort_by": "relevance"})
                if r.status_code == 200:
                    results = r.json()
                    for item in results:
                        if item.get('type') == 'video' and item.get('videoId'):
                            return item['videoId'], item.get('title', query)
            except Exception as e:
                logger.warning(f"Invidious {instance} failed: {e}")
                continue

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            url = "https://www.youtube.com/results"
            r = await client.get(url, params={"search_query": query, "sp": "EgIQAQ%3D%3D"})
            if r.status_code == 200:
                text = r.text
                idx = text.find('"videoId":"')
                if idx > 0:
                    start = idx + 11
                    end = text.find('"', start)
                    video_id = text[start:end]

                    tidx = text.find('"title":{"runs":[{"text":"', start)
                    if tidx > 0:
                        tstart = tidx + 26
                        tend = text.find('"', tstart)
                        title = text[tstart:tend]
                    else:
                        title = query

                    return video_id, title
    except Exception as e:
        logger.error(f"YouTube search failed: {e}")

    return None, None


async def download_via_rapidapi(video_id: str, title: str):
    """Download MP3 via RapidAPI YouTube MP3"""
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            url = "https://youtube-mp36.p.rapidapi.com/dl"
            headers = {
                "Content-Type": "application/json",
                "x-rapidapi-host": "youtube-mp36.p.rapidapi.com",
                "x-rapidapi-key": RAPIDAPI_KEY
            }

            r = await client.get(url, headers=headers, params={"id": video_id})
            logger.info(f"RapidAPI response: {r.status_code}")

            if r.status_code != 200:
                logger.error(f"RapidAPI error: {r.text[:200]}")
                return None

            data = r.json()
            logger.info(f"RapidAPI data: {data}")

            if data.get('status') == 'ok':
                download_url = data.get('link')
                if not download_url:
                    logger.error("No download link in response")
                    return None

                safe_title = data.get('title', title).replace('/', '-').replace('\\', '-')[:80]
                file_path = os.path.join(DOWNLOADS_DIR, f"{video_id}.mp3")

                r2 = await client.get(download_url)
                if r2.status_code == 200:
                    with open(file_path, 'wb') as f:
                        f.write(r2.content)
                    logger.info(f"Downloaded: {os.path.getsize(file_path)} bytes")
                    return (file_path, safe_title)
                else:
                    logger.error(f"Download failed: {r2.status_code}")
                    return None
            else:
                logger.error(f"RapidAPI status not ok: {data}")
                return None

    except Exception as e:
        logger.error(f"RapidAPI error: {e}", exc_info=True)
        return None


async def run_bot():
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        logger.error("BOT_TOKEN belum diisi!")
        return

    logger.info(f"RapidAPI key: {'SET' if RAPIDAPI_KEY else 'MISSING'}")

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


async def handle_index(request):
    return web.json_response({"status": "ok", "engine": "rapidapi"})


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


async def main():
    logger.info("Starting with RapidAPI engine...")
    await asyncio.gather(
        run_bot(),
        start_web_server()
    )


if __name__ == '__main__':
    asyncio.run(main())
