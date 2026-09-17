import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Setup logging biar kita tau ada error apa
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Token bot dari BotFather (GANTI DENGAN TOKEN LU!)
BOT_TOKEN = os.getenv('BOT_TOKEN', 'TOKEN_LO_DISINI')

# Folder buat temporary storage
DOWNLOADS_DIR = 'downloads'


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
    """Handler buat command .p judul lagu atau pesan biasa"""
    # Ambil query dari command /p atau dari pesan biasa
    if context.args:
        query = ' '.join(context.args)
    elif update.message and update.message.text:
        text = update.message.text
        # Cek apakah pesan diawali dengan .p
        if text.lower().startswith('.p '):
            query = text[3:].strip()
        else:
            # Kalau pesan biasa (bukan command), skip
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

    # Kirim pesan loading
    loading_msg = await update.message.reply_text(
        f"🔍 **Mencari:** {query}... ⏳\n"
        "Sabar ya, gue download dulu!",
        parse_mode='Markdown'
    )

    try:
        # Download audio dari YouTube
        audio_path = await download_audio(query)

        if audio_path and os.path.exists(audio_path):
            # Cek file size (Render free plan limit ~512MB RAM)
            file_size = os.path.getsize(audio_path)
            if file_size > 50 * 1024 * 1024:  # 50MB limit
                await loading_msg.edit_text(
                    "❌ **File terlalu besar!** ( > 50MB)\n"
                    "Coba judul lagu yang lain.",
                    parse_mode='Markdown'
                )
                os.remove(audio_path)
                return

            # Kirim file audio ke user
            with open(audio_path, 'rb') as audio:
                await update.message.reply_audio(
                    audio=audio,
                    title=query[:100],  # Telegram limit 100 char
                    performer="YouTube Audio"
                )

            # Hapus file setelah dikirim (hemat memory!)
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


async def download_audio(query: str) -> str:
    """Download audio dari YouTube berdasarkan query"""
    try:
        # Bikin folder downloads kalo belum ada
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

        # Hapus file lama di downloads (hemat memory)
        for f in os.listdir(DOWNLOADS_DIR):
            file_path = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(file_path):
                os.remove(file_path)

        # Command yt-dlp buat download audio
        cmd = [
            'yt-dlp',
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '5',  # Quality medium (hemat kuota)
            '--max-filesize', '50M',  # Max 50MB
            '--no-playlist',  # Jangan download playlist
            '--no-warnings',  # Minimize warnings
            '--quiet',  # Quiet mode
            '--no-overwrites',  # Jangan timpa file
            '--default-search', 'ytsearch1:',  # Cari di YouTube, ambil 1 hasil
            '--output', f'{DOWNLOADS_DIR}/%(id)s.%(ext)s',
            f'ytsearch1:{query}'
        ]

        # Jalankan command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"yt-dlp error: {stderr.decode()}")
            return None

        # Cari file yang baru di-download
        files = os.listdir(DOWNLOADS_DIR)
        if files:
            # Ambil file terbaru
            mp3_files = [f for f in files if f.endswith('.mp3')]
            if mp3_files:
                latest_file = max(
                    [os.path.join(DOWNLOADS_DIR, f) for f in mp3_files],
                    key=os.path.getmtime
                )
                return latest_file

            # Kalau gak ada mp3, ambil file apapun yang terbaru
            latest_file = max(
                [os.path.join(DOWNLOADS_DIR, f) for f in files],
                key=os.path.getmtime
            )
            return latest_file

        return None

    except Exception as e:
        logger.error(f"Download error: {e}")
        return None


def main():
    """Fungsi utama buat jalanin bot"""
    # Cek token
    if BOT_TOKEN == 'TOKEN_LO_DISINI':
        print("❌ ERROR: Token bot belum diisi!")
        print("Silakan isi token di environment variable BOT_TOKEN")
        print("Atau ganti langsung di kode bot.py")
        return

    # Bikin application
    app = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("p", search_and_send))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_send))

    # Jalanin bot
    print("🤖 Bot Musik Mulai Jalan! 🎵")
    print("Tekan Ctrl+C buat stop")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
