import time
import os
import asyncio
import logging
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from pyrogram import Client, filters
from pyrogram.types import Message

# 🔧 Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__) 

# 🟢 Spotify credentials
client_secret = "97d40c2c7b7948589df58d838b8e9e68"
client_id = "c6e8b0da7751415e848a97f309bc057d"
auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(auth_manager=auth_manager)

DEFAULT_QUERIES = [
    "bollywood hits", "top hindi songs", "indian classical", "desi hip hop", "punjabi hits",
    "gujarati garba", "indian devotional", "arijit singh", "shreya ghoshal", "indian pop",
    "tamil hits", "telugu hits", "marathi hits", "rajasthani folk", "bengali songs",
    "indian rock", "indian indie", "bhajan", "sufi music india", "indian rap",
    "indian electronic", "fusion music india", "hindi sad songs", "hindi romantic",
    "hindi dance", "regional indian music", "hindi remix", "indian party songs"
]

@Client.on_message(filters.command("playlist"))
async def get_custom_playlists(client: Client, message: Message):
    try:
        args = message.text.split(None, 1)
        if len(args) > 1:
            user_input = args[1].lower()
            queries = [q.strip() for q in user_input.replace(",", " ").split() if q.strip()]
        else:
            queries = DEFAULT_QUERIES

        if not queries:
            return await message.reply("❌ Please provide valid search terms.")

        await message.reply(f"🔍 Searching playlists for: `{', '.join(queries)}`", quote=True)
        logger.info(f"Searching for queries: {queries}")

        playlists_dict = {}

        for query in queries:
            for offset in range(0, 500, 50):
                try:
                    results = sp.search(q=query, type="playlist", limit=50, offset=offset)
                    await asyncio.sleep(0.5)
                    logger.info(f"Queried '{query}' at offset {offset}")
                except Exception as err:
                    logger.warning(f"Error while searching: {query} @ offset {offset}: {err}")
                    continue

                playlists_data = results.get("playlists") if results else None
                if not playlists_data:
                    continue

                items = playlists_data.get("items", [])
                for item in items:
                    if not item:
                        continue
                    name = item.get("name")
                    playlist_id = item.get("id")
                    if name and playlist_id:
                        url = f"https://open.spotify.com/playlist/{playlist_id}"
                        playlists_dict[name] = url

        total = len(playlists_dict)
        if total == 0:
            return await message.reply("❌ No playlists found. Try again later.")

        file_name = f"custom_playlists_{int(time.time())}.txt"
        with open(file_name, "w", encoding="utf-8") as f:
            for idx, (name, url) in enumerate(sorted(playlists_dict.items()), 1):
                f.write(f"{idx}. {name} - {url}\n")

        await message.reply_document(
            file_name,
            caption=f"✅ Found `{total}` unique playlists for your search."
        )

        # Remove file after sending to keep your server clean
        os.remove(file_name)

    except Exception as e:
        logger.exception("❌ Final error occurred.")
        await message.reply(f"❌ Final Error: `{e}`")
