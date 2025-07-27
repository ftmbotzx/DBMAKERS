import logging
from pyrogram import Client, filters
from pyrogram.types import Message
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
import os
import asyncio
import time 


# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# Spotify API credentials
SPOTIFY_CLIENT_ID = "c6e8b0da7751415e848a97f309bc057d"
SPOTIFY_CLIENT_SECRET = "97d40c2c7b7948589df58d838b8e9e68"

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

SPOTIFY_PLAYLIST_REGEX = r"https://open\.spotify\.com/playlist/([a-zA-Z0-9]+)"

@Client.on_message(filters.command("creators") & filters.reply)
async def get_creators_from_playlists(client: Client, message: Message):
    # Check if replied message has document
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply("⚠️ Please reply to a `.txt` file containing Spotify playlist links.")

    # Download the replied .txt file
    file_path = await message.reply_to_message.download()
    creators_dict = {}

    try:
        # Read content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract playlist IDs
        playlist_ids = re.findall(SPOTIFY_PLAYLIST_REGEX, content)
        total = len(playlist_ids)
        logger.info(f"Found {total} playlists to process.")
        status_msg = await message.reply(f"🌀 Found {total} playlists. Extracting creators...")

        for idx, pid in enumerate(playlist_ids, start=1):
            try:
                playlist_info = sp.playlist(pid)
                owner = playlist_info.get("owner", {})
                owner_name = owner.get("display_name", "Unknown")
                owner_id = owner.get("id", None)
                if owner_id:
                    owner_url = f"https://open.spotify.com/user/{owner_id}"
                else:
                    owner_url = "N/A"

                # Add to dict unique creators by owner name (or owner id)
                creators_dict[owner_name] = owner_url
                logger.info(f"Got creator: {owner_name} ({owner_url}) from playlist {pid}")
            except Exception as e:
                logger.warning(f"Error fetching playlist {pid}: {e}")

            if idx % 10 == 0 or idx == total:
                await status_msg.edit(f"🔍 Extracted creators from {idx}/{total} playlists...")

            await asyncio.sleep(0.5)  # To avoid rate limits

        if not creators_dict:
            return await message.reply("❌ No creators found.")

        timestamp = int(time.time())
        result_file = f"creators_list_{timestamp}.txt"
        with open(result_file, "w", encoding="utf-8") as f:
            for idx, (name, url) in enumerate(sorted(creators_dict.items()), 1):
                f.write(f"{idx}. {name} - {url}\n")
              
        await message.reply_document(result_file, caption=f"✅ Found {len(creators_dict)} unique playlist creators.")
        os.remove(result_file)

    except Exception as e:
        logger.exception("An error occurred while extracting creators.")
        await message.reply(f"❌ Error: {e}")

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
