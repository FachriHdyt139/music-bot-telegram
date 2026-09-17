import os
import logging
import asyncio
import subprocess
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
            await loading.edit_text("❌ **Lagu tidak ditemukan!**")
            return

        logger.info(f"Found: {title} (ID: {video_id})")
        await loading.edit_text(f"📥 **Download:** {title}...")

        result = await download_mp3(video_id, title)
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
                return
            if os.path.exists(audio_path):
                os.remove(audio_path)

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
    """Search YouTube via HTML scraping"""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(
                "https://www.youtube.com/results",
                params={"search_query": query, "sp": "EgIQAQ%3D%3D"},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            if r.status_code == 200:
                text = r.text
                idx = text.find('"videoId":"')
                if idx > 0:
                    start = idx + 11
                    end = text.find('"', start)
                    video_id = text[start:end]

                    tidx = text.find('"title":{"runs":[{"text":"', start)
                    title = query
                    if tidx > 0:
                        tstart = tidx + 26
                        tend = text.find('"', tstart)
                        title = text[tstart:tend]

                    return video_id, title
    except Exception as e:
        logger.error(f"Search failed: {e}")
    return None, None


def download_ytdlp(video_id: str, title: str):
    """Download via yt-dlp Python API (blocking, run in executor)"""
    try:
        import yt_dlp

        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        output_path = os.path.join(DOWNLOADS_DIR, f"{video_id}.mp3")

        ydl_opts = {
            'format': 'bestaudio/best',
            'extract_audio': True,
            'audio_format': 'mp3',
            'audio_quality': '5',
            'outtmpl': os.path.join(DOWNLOADS_DIR, f"{video_id}.%(ext)s"),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': {'player_client': ['web']}},
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f'https://www.youtube.com/watch?v={video_id}'])

        if os.path.exists(output_path):
            return output_path

        for f in os.listdir(DOWNLOADS_DIR):
            if f.startswith(video_id) and f.endswith(('.mp3', '.m4a', '.webm', '.opus')):
                return os.path.join(DOWNLOADS_DIR, f)

        return None
    except Exception as e:
        logger.error(f"yt-dlp failed: {e}")
        return None


async def download_rapidapi(video_id: str, title: str):
    """Download via RapidAPI + curl subprocess"""
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOADS_DIR, f"{video_id}.mp3")

    try:
        proc = await asyncio.create_subprocess_exec(
            'curl', '-s',
            f'https://youtube-mp36.p.rapidapi.com/dl?id={video_id}',
            '-H', 'x-rapidapi-host: youtube-mp36.p.rapidapi.com',
            '-H', f'x-rapidapi-key: {RAPIDAPI_KEY}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            logger.error("RapidAPI call failed")
            return None

        import json
        data = json.loads(stdout.decode())
        logger.info(f"RapidAPI: {data.get('status')}, size={data.get('filesize')}, dur={data.get('duration')}")

        if data.get('status') != 'ok' or not data.get('link'):
            return None

        link = data['link']
        song_title = data.get('title', title)

        proc2 = await asyncio.create_subprocess_exec(
            'curl', '-s', '-o', file_path, '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            '-H', 'Referer: https://youtube-mp36.p.rapidapi.com/',
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc2.communicate()

        if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
            ct = subprocess.run(
                ['file', '--brief', file_path],
                capture_output=True, text=True
            ).stdout.strip()

            if 'Audio' in ct or 'MPEG' in ct or 'MP3' in ct or 'ID3' in ct:
                logger.info(f"RapidAPI OK: {os.path.getsize(file_path)} bytes")
                return (file_path, song_title)
            else:
                logger.warning(f"Bad file type: {ct}")
                os.remove(file_path)
                return None

        if os.path.exists(file_path):
            os.remove(file_path)
        return None

    except Exception as e:
        logger.error(f"RapidAPI failed: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        return None


async def download_mp3(video_id: str, title: str):
    """Try yt-dlp first, then RapidAPI fallback"""

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, download_ytdlp, video_id, title)
    if result:
        return (result, title)

    logger.info("yt-dlp failed, trying RapidAPI...")
    return await download_rapidapi(video_id, title)


async def run_bot():
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        logger.error("BOT_TOKEN belum diisi!")
        return

    logger.info(f"RapidAPI: {'SET' if RAPIDAPI_KEY else 'MISSING'}")

    try:
        import yt_dlp
        logger.info(f"✅ yt-dlp available: {yt_dlp.version.__version__}")
    except ImportError:
        logger.warning("⚠️ yt-dlp not installed, using RapidAPI only")

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
    return web.json_response({"status": "ok", "engine": "ytdlp+rapidapi"})


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
    logger.info("Starting...")
    await asyncio.gather(
        run_bot(),
        start_web_server()
    )


if __name__ == '__main__':
    asyncio.run(main())
