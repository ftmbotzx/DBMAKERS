
import os
import time
import logging
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from plugins.advanced_spotify_manager import get_spotify_manager
import re

# -------- Logger Setup --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def extract_user_id(spotify_url: str) -> str:
    match = re.search(r"open\.spotify\.com/user/([a-zA-Z0-9]+)", spotify_url)
    if match:
        return match.group(1)
    return None

@Client.on_message(filters.command("user") & filters.reply & filters.document)
async def process_user_file(client: Client, message: Message):
    doc = message.reply_to_message.document
    if not doc.file_name.endswith(".txt"):
        await message.reply("❗ Please reply to a valid .txt file containing lines in user - spotify_url format.")
        return

    file_path = await client.download_media(doc)

    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    total_users = len(lines)
    if total_users == 0:
        await message.reply("⚠️ The file is empty or has no valid lines.")
        return

    status_msg = await message.reply(f"⏳ Starting to process {total_users} users from the file...")

    # Initialize Spotify manager
    manager = get_spotify_manager()
    manager.set_telegram_client(client)

    global_total_tracks = 0
    all_users_track_ids = []

    for user_index, line in enumerate(lines, start=1):
        if "-" not in line:
            await message.reply(f"⚠️ Skipping invalid format line: {line}. Expected format: user - spotify_url")
            continue

        user_name, url = map(str.strip, line.split("-", 1))
        user_id = extract_user_id(url)

        if not user_id:
            await message.reply(f"⚠️ Invalid Spotify URL for user {user_name}: {url}")
            continue

        try:
            await status_msg.edit(
                f"🔍 [{user_index}/{total_users}] Fetching playlists for user: **{user_name}** ({user_id})..."
            )

            # Get Spotify client
            spotify_client = await manager.get_spotify_client()
            playlists = await spotify_client.user_playlists(user_id)
            
            if not playlists or not playlists.get('items'):
                await status_msg.edit(f"⚠️ No public playlists found for user **{user_name}**.")
                continue

            total_playlists = 0
            total_tracks_user = 0
            total_playlists_count = playlists.get("total")
            user_track_ids = []

            while playlists:
                for playlist in playlists['items']:
                    total_playlists += 1
                    pid = playlist['id']
                    pname = playlist['name']
                    
                    tracks = await spotify_client.playlist_tracks(pid)
                    playlist_tracks_count = 0

                    while tracks:
                        if 'items' in tracks:
                            for item in tracks['items']:
                                track = item.get('track')
                                if track and track.get('id'):
                                    user_track_ids.append(track['id'])
                                    total_tracks_user += 1
                                    playlist_tracks_count += 1

                        if tracks.get('next'):
                            tracks = await spotify_client.next(tracks)
                        else:
                            tracks = None

                    global_total_tracks += playlist_tracks_count

                    await status_msg.edit(
                        f"🔄 Processing User {user_index} / {total_users}\n"
                        f"🎵 Tracks found in current playlist: {playlist_tracks_count}\n"
                        f"📀 Playlists processed for this user: {total_playlists} / {total_playlists_count or '?'}\n"
                        f"🎵 Total tracks for this user: {total_tracks_user}\n\n"
                        f"👥 Total users processed: {user_index} / {total_users}\n"
                        f"🎧 Total tracks collected from ALL users: {global_total_tracks}"
                    )
                    await asyncio.sleep(1)

                if playlists.get('next'):
                    playlists = await spotify_client.next(playlists)
                else:
                    playlists = None

            unique_user_tracks = list(set(user_track_ids))
            all_users_track_ids.extend(unique_user_tracks)

            await status_msg.edit(
                f"✅ Completed [{user_index}/{total_users}]: **{user_name}**\n"
                f"📀 Total playlists: {total_playlists}\n"
                f"🎵 Unique tracks: {len(unique_user_tracks)}\n"
                f"🎧 Total tracks collected from ALL users: {global_total_tracks}"
            )

        except Exception as e:
            await message.reply(f"❌ Error fetching tracks for **{user_name}**: {e}")
            logger.error(f"Error fetching tracks for user {user_id}: {e}")

    # After processing all users, write all unique tracks to one file
    all_unique_tracks = list(set(all_users_track_ids))
    timestamp = int(time.time())
    file_name = f"all_users_tracks_{timestamp}.txt"

    with open(file_name, "w", encoding="utf-8") as f:
        for tid in all_unique_tracks:
            f.write(f"{tid}\n")

    await client.send_document(
        chat_id=message.chat.id,
        document=file_name,
        caption=f"✅ Total unique track IDs from all users: {len(all_unique_tracks)}"
    )
    os.remove(file_name)
    os.remove(file_path)

    await status_msg.edit("🎉 All users processed. Check your chat for the combined tracks file!")
