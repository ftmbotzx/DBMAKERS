import os
import subprocess
import logging
from pyrogram import Client, filters


FFMPEG_PATH = "/usr/bin/ffmpeg"
DOWNLOAD_PATH = "./downloads"

if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)

# === Logging setup ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# === Pyrogram Bot ===
app = Client

@app.on_message(filters.command("dl") & filters.private)
async def download_song(client, message):
    if len(message.command) < 2:
        await message.reply("❌ Usage:\n/dl <spotify_link>")
        return

    url = message.command[1]
    status = await message.reply("⏳ Downloading, please wait...")
    logger.info(f"Received URL: {url}")

    cmd = [
        "spotdl",
        "download",
        url,
        "--output", DOWNLOAD_PATH,
        "--format", "mp3",
        "--bitrate", "320k",
        "--ffmpeg", FFMPEG_PATH
    ]

    logger.info(f"Running command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )

        logger.info(f"SpotDL STDOUT:\n{result.stdout}")
        logger.info(f"SpotDL STDERR:\n{result.stderr}")

    except subprocess.CalledProcessError as e:
        logger.error(f"SpotDL failed! STDOUT:\n{e.stdout}")
        logger.error(f"SpotDL failed! STDERR:\n{e.stderr}")

        error_msg = f"❌ SpotDL failed:\n\nSTDERR:\n{e.stderr}"
        if len(error_msg) > 4096:
            error_msg = error_msg[:4000] + "\n\n[...output truncated]"
        await status.edit(error_msg)
        return

    files = [f for f in os.listdir(DOWNLOAD_PATH) if f.endswith(".mp3")]
    if not files:
        await status.edit("❌ Download failed, no file found.")
        logger.warning("Download folder empty after SpotDL run.")
        return

    files.sort(key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_PATH, x)), reverse=True)
    file_path = os.path.join(DOWNLOAD_PATH, files[0])

    logger.info(f"Sending file: {file_path}")

    await client.send_audio(chat_id=message.chat.id, audio=file_path)
    os.remove(file_path)

    logger.info(f"Deleted file after sending: {file_path}")

    await status.edit("✅ Downloaded & sent successfully!")

