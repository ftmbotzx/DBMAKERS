import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified
import re
import os
import asyncio
import time
from plugins.advanced_spotify_manager import get_spotify_manager

# -------- Logger Setup --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# -------- Regex to extract playlist IDs --------
SPOTIFY_PLAYLIST_REGEX = r"https://open\.spotify\.com/playlist/([a-zA-Z0-9]+)"

# -------- Extract tracks from one playlist --------
async def extract_tracks_from_playlist(playlist_id, max_retries=3):
    for attempt in range(max_retries):
        try:
            manager = get_spotify_manager()
            spotify_client = await manager.get_spotify_client()

            results = await spotify_client.playlist_tracks(playlist_id)
            tracks = []

            while results:
                if 'items' in results:
                    for item in results['items']:
                        if item and item.get('track') and item['track'].get('id'):
                            tracks.append(item['track']['id'])

                if results.get('next'):
                    results = await spotify_client.next(results)
                else:
                    break

            return tracks
        except Exception as e:
            logger.error(f"Error extracting tracks from playlist {playlist_id} (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            else:
                return []

# -------- Command Handler --------
@Client.on_message(filters.command("extracttracks") & filters.reply)
async def extract_from_txt(client: Client, message: Message):
    if not message.reply_to_message.document:
        return await message.reply("⚠️ Reply to a `.txt` file containing Spotify playlist links.")

    # Parse start index from command args, default 0
    try:
        start_index = int(message.command[1]) if len(message.command) > 1 else 0
    except:
        return await message.reply("⚠️ Invalid start index. Usage: /extracttracks 0")

    file_path = await message.reply_to_message.download()
    final_track_ids = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        playlist_ids = re.findall(SPOTIFY_PLAYLIST_REGEX, content)
        total = len(playlist_ids)

        if start_index >= total:
            return await message.reply(f"⚠️ Start index {start_index} is out of range (total {total} playlists).")

        logger.info(f"📂 Found {total} playlist links.")
        logger.info(f"🎯 Starting extraction from playlist index {start_index + 1}/{total}")

        status = await message.reply(
            f"🌀 Found {total} playlists.\n➡️ Starting from index {start_index + 1}..."
        )

        batch_counter = 1
        batch_start = start_index + 1  # human-readable playlist number (1-based)
        batch_tracks = []

        for idx in range(start_index, total):
            pid = playlist_ids[idx]
            logger.info(f"Processing playlist {idx + 1}/{total}")

            ids = await extract_tracks_from_playlist(pid)
            batch_tracks.extend(ids)
            final_track_ids.extend(ids)

            # Every 500 playlists or at the end, send batch file
            if (idx + 1 - start_index) % 500 == 0 or (idx + 1) == total:
                batch_end = idx + 1
                unique_tracks = list(set(batch_tracks))
                timestamp = int(time.time())
                filename = f"tracks_batch_{batch_start}_to_{batch_end}_{timestamp}.txt"

                with open(filename, "w") as f:
                    f.write("\n".join(unique_tracks))

                await message.reply_document(filename, caption=f"📦 Batch {batch_counter} sent: playlists {batch_start} to {batch_end}")

                logger.info(f"Batch {batch_counter} sent: playlists {batch_start} to {batch_end}")

                os.remove(filename)
                batch_counter += 1
                batch_start = batch_end + 1
                batch_tracks.clear()

            # Edit progress message every 10 playlists (reduce telegram API calls)
            if (idx + 1) % 10 == 0 or (idx + 1) == total:
                try:
                    await status.edit(f"🔍 Extracted {idx + 1}/{total} playlists.")
                except MessageNotModified:
                    pass
                except Exception as e:
                    logger.error(f"Failed to update status: {e}")

            # Reduced sleep time for better performance
            await asyncio.sleep(0.2)

        await status.edit(f"✅ Extraction complete! Total playlists processed: {total - start_index}. Total unique tracks: {len(set(final_track_ids))}")

    except Exception as e:
        logger.exception("An error occurred during extraction.")
        await message.reply(f"❌ Error: {e}")

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

async def extract_all_playlists():
    pass

async def main():
    await extract_all_playlists()

if __name__ == "__main__":
    asyncio.run(main())