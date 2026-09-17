# 🎵 Music Bot Telegram

Bot Telegram untuk memutar lagu dari YouTube. Ketik `/p judul lagu` dan bot akan mengirim file MP3-nya.

## Fitur

- Cari dan putar lagu dari YouTube
- Format MP3 (hemat kuota)
- Deploy gratis di Render
- Auto-cleanup file setelah dikirim

## Cara Pakai

1. Kirim `/start` ke bot
2. Kirim `/p judul lagu` (contoh: `/p sampai jumpa`)
3. Bot akan mencari dan mengirim file MP3

## Setup (Development)

### 1. Buat Bot Telegram

1. Buka Telegram, cari @BotFather
2. Kirim `/newbot`
3. Ikuti instruksi, simpan token-nya

### 2. Install Dependencies

```bash
# Buat virtual environment
python -m venv venv

# Aktifkan
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install packages
pip install -r requirements.txt

# Install yt-dlp (system-wide)
pip install yt-dlp
```

### 3. Setup Token

```bash
# Copy .env.example jadi .env
cp .env.example .env

# Edit .env, isi token bot
# BOT_TOKEN=token_dari_botfather
```

### 4. Jalankan

```bash
python bot.py
```

## Deploy ke Render (Gratis)

1. Upload project ke GitHub
2. Buka https://render.com
3. New + → Worker
4. Pilih repo GitHub
5. Isi:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
6. Tambah Environment Variable:
   - Key: `BOT_TOKEN`
   - Value: `token_bot_lu`
7. Klik Create Worker

## Error

| Error | Solusi |
|-------|--------|
| Token salah | Cek ulang di BotFather |
| yt-dlp not found | `pip install yt-dlp` |
| File terlalu besar | Coba judul lain |
| Cold start | Tunggu 30 detik |

## License

MIT - Gratis bebas dipake!
