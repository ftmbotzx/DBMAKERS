from pyrogram import Client, filters
from pyrogram.types import Message
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import logging
import time
import os

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENT_ID = "c6e8b0da7751415e848a97f309bc057d"
CLIENT_SECRET = "97d40c2c7b7948589df58d838b8e9e68"

auth_manager = SpotifyClientCredentials(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
sp = spotipy.Spotify(auth_manager=auth_manager)


@Client.on_message(filters.command("allartists"))
async def get_all_indian_artists(client: Client, message: Message):
    try:
        if len(message.command) > 1:
            # User ne queries diye hain
            user_queries = message.text.split(None, 1)[1]  # Command ke baad saara text
            queries = [q.strip() for q in user_queries.split(",") if q.strip()]
        else:
            # Default queries
            queries = [
                "top hindi songs", "top bollywood", "top punjabi hits", "latest gujarati songs",
                "indian classical", "indie india", "top tamil hits", "top telugu songs",
                "top marathi tracks", "indian rap", "indian pop", "arijit singh", "shreya ghoshal",
                "regional india", "indian devotional", "desi hip hop"
            ]

        logger.info(f"Searching artists for queries: {queries}")

        artists_dict = {}

        for query in queries:
            results = sp.search(q=query, type='track', limit=50, market='IN')
            for item in results['tracks']['items']:
                for artist in item['artists']:
                    artists_dict[artist['name']] = f"https://open.spotify.com/artist/{artist['id']}"

        sorted_artists = sorted(artists_dict.items())
        total_count = len(sorted_artists)

        text = f"🇮🇳 **All Indian Artist List (Auto Compiled)**\n🎧 **Total Unique Artists Found:** {total_count}\n\n"
        for idx, (name, url) in enumerate(sorted_artists, 1):
            text += f"{idx}. [{name}]({url})\n"

        # Unique filename with timestamp
        timestamp = int(time.time())
        file_name = f"indian_artists_list_{timestamp}.txt"

        # Save raw text file
        plain_text = "\n".join([f"{idx}. {name} - {url}" for idx, (name, url) in enumerate(sorted_artists, 1)])
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(plain_text)

        await message.reply_document(
            file_name,
            caption=f"✅ Found `{total_count}` unique Indian artists for queries: {', '.join(queries)}."
        )

        # Remove file after sending
        if os.path.exists(file_name):
            os.remove(file_name)

    except Exception as e:
        logger.exception("Error in get_all_indian_artists")
        await message.reply(f"❌ Error: `{e}`")
