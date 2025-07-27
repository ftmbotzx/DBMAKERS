import os
import time
import json
import re
import asyncio
from datetime import datetime
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from plugins.advanced_spotify_manager import get_spotify_manager
from database.db import db
from pyrogram.errors import FloodWait

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Extract Spotify ID from URL
def extract_spotify_id(url):
    """Extract Spotify ID from various URL formats"""
    patterns = [
        r'spotify:playlist:([a-zA-Z0-9]+)',
        r'open\.spotify\.com/playlist/([a-zA-Z0-9]+)',
        r'spotify\.com/playlist/([a-zA-Z0-9]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

# Extract tracks from playlist using advanced manager
async def extract_playlist_tracks(spotify_client, playlist_id):
    """Extract all tracks from a playlist using the advanced manager"""
    try:
        tracks = []
        result = await spotify_client.playlist_tracks(playlist_id)
        
        while result:
            if 'items' in result:
                for item in result['items']:
                    if item and item.get('track') and item['track'].get('id'):
                        tracks.append(item['track']['id'])
            
            # Get next page if available
            if result.get('next'):
                result = await spotify_client.next(result)
            else:
                break
                
        return tracks
        
    except Exception as e:
        logger.error(f"Error extracting tracks from playlist {playlist_id}: {e}")
        return []

@Client.on_message(filters.command("extract") & filters.private)
async def extract_tracks_command(client: Client, message: Message):
    """Extract tracks from Spotify playlists"""
    
    # Set up manager
    manager = get_spotify_manager()
    manager.set_telegram_client(client)
    
    try:
        # Get Spotify client
        spotify_client = await manager.get_spotify_client()
        
        status_msg = await message.reply("🎵 **Starting Track Extraction**\n⏳ Loading playlists...")
        
        # Load playlist URLs from database or file
        playlist_collection = db.playlists
        playlists_cursor = playlist_collection.find({})
        playlists = await playlists_cursor.to_list(length=None)
        
        if not playlists:
            await status_msg.edit_text("❌ No playlists found in database!")
            return
        
        # Create output file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"extracted_tracks_{timestamp}.txt"
        
        total_playlists = len(playlists)
        total_tracks = 0
        processed = 0
        
        await status_msg.edit_text(f"🎵 **Extracting from {total_playlists} playlists**\n⏳ Processing...")
        
        with open(output_file, 'w') as f:
            for i, playlist_data in enumerate(playlists):
                processed += 1
                playlist_url = playlist_data.get('url', '')
                playlist_id = extract_spotify_id(playlist_url)
                
                if not playlist_id:
                    logger.warning(f"Could not extract ID from URL: {playlist_url}")
                    continue
                
                # Extract tracks
                tracks = await extract_playlist_tracks(spotify_client, playlist_id)
                
                if tracks:
                    # Write tracks to file
                    for track_id in tracks:
                        f.write(f"{track_id}\n")
                    
                    total_tracks += len(tracks)
                    logger.info(f"✅ Extracted {len(tracks)} tracks from playlist {playlist_id}")
                else:
                    logger.warning(f"❌ No tracks extracted from playlist {playlist_id}")
                
                # Update progress every 10 playlists
                if processed % 10 == 0:
                    progress = (processed / total_playlists) * 100
                    await status_msg.edit_text(
                        f"🎵 **Track Extraction Progress**\n"
                        f"📊 {processed}/{total_playlists} playlists ({progress:.1f}%)\n"
                        f"🎶 {total_tracks} tracks extracted\n"
                        f"📁 Saving to: `{output_file}`"
                    )
                
                # Small delay to prevent overwhelming
                await asyncio.sleep(0.1)
        
        # Final status
        await status_msg.edit_text(
            f"✅ **Extraction Complete!**\n"
            f"📊 Processed: {processed}/{total_playlists} playlists\n"
            f"🎶 Total tracks: {total_tracks}\n"
            f"📁 Saved to: `{output_file}`\n"
            f"⏱️ Client used: `{manager.get_current_client_id()[:8]}...`"
        )
        
        # Log completion to Telegram
        await manager._log_to_telegram(
            f"✅ **Track Extraction Completed**\n"
            f"📊 {processed} playlists processed\n"
            f"🎶 {total_tracks} tracks extracted\n"
            f"📁 File: {output_file}"
        )
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        await message.reply(f"❌ **Extraction Failed**\n`{str(e)}`")

def extract_user_id(url):
    match = re.search(r"spotify\.com/user/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)
    return None

@Client.on_message(filters.command("ur"))
async def user_tracks_split(client, message):
    if len(message.command) < 2:
        await message.reply("❗ Usage: `/ur <spotify_user_link>`")
        return

    user_url = message.command[1]
    user_id = extract_user_id(user_url)

    if not user_id:
        await message.reply("⚠️ Invalid Spotify user link!")
        return

    try:
        # Initialize Spotify manager
        manager = get_spotify_manager()
        manager.set_telegram_client(client)
        sp = await manager.get_spotify_client()

        status = await message.reply(f"⏳ Fetching playlists for `{user_id}`...")

        playlists = await sp.user_playlists(user_id)
        if not playlists['items']:
            await status.edit("⚠️ No public playlists found for this user.")
            return

        all_ids = []
        total_tracks = 0
        total_playlists = 0

        while playlists:
            for playlist in playlists['items']:
                total_playlists += 1
                pname = playlist['name']
                pid = playlist['id']

                await status.edit(
                    f"🔍 Processing playlist: **{pname}**\n"
                    f"✅ Playlists done: {total_playlists}\n"
                    f"🎵 Tracks so far: {total_tracks}"
                )

                tracks = await sp.playlist_tracks(pid)

                while tracks:
                    for item in tracks['items']:
                        track = item['track']
                        if track:
                            tid = track['id']
                            all_ids.append(tid)
                            total_tracks += 1

                            if total_tracks % 200 == 0:
                                await status.edit(
                                    f"📦 Still fetching...\n"
                                    f"✅ Playlists done: {total_playlists}\n"
                                    f"🎵 Tracks so far: {total_tracks}"
                                )

                    if tracks.get('next'):
                        tracks = await sp.next(tracks)
                    else:
                        tracks = None

            if playlists.get('next'):
                playlists = await sp.next(playlists)
            else:
                playlists = None

        # Split into chunks of 5000
        chunk_size = 5000
        chunks = [all_ids[i:i + chunk_size] for i in range(0, len(all_ids), chunk_size)]

        part_number = 1
        for chunk in chunks:
            file_name = f"{user_id}_tracks_part{part_number}.txt"
            with open(file_name, "w", encoding="utf-8") as f:
                for tid in chunk:
                    f.write(f"{tid}\n")

            await client.send_document(
                chat_id=message.chat.id,
                document=file_name,
                caption=f"✅ `{user_id}` | Part {part_number} | {len(chunk)} track IDs"
            )
            part_number += 1

        await status.edit(
            f"🎉 **Done!** Total playlists: `{total_playlists}` | Total tracks: `{total_tracks}` | Files: `{len(chunks)}`"
        )

    except Exception as e:
        await status.edit(f"❌ Error: `{e}`")


@Client.on_message(filters.command("user"))
async def usernn_count(client, message):
    if len(message.command) < 2:
        await message.reply("❗ Usage: `/usercount <spotify_user_link>`")
        return

    user_url = message.command[1]
    user_id = extract_user_id(user_url)

    if not user_id:
        await message.reply("⚠️ Invalid Spotify user link!")
        return

    try:
        # Initialize Spotify manager
        manager = get_spotify_manager()
        manager.set_telegram_client(client)
        sp = await manager.get_spotify_client()

        playlists = await sp.user_playlists(user_id)
        if not playlists['items']:
            await message.reply("⚠️ No public playlists found for this user.")
            return

        total_playlists = 0
        total_tracks = 0

        while playlists:
            for playlist in playlists['items']:
                total_playlists += 1
                total_tracks += playlist['tracks']['total']
            if playlists.get('next'):
                playlists = await sp.next(playlists)
            else:
                playlists = None

        await message.reply(
            f"👤 **User:** `{user_id}`\n"
            f"📚 **Total Playlists:** {total_playlists}\n"
            f"🎵 **Total Tracks in All Playlists:** {total_tracks}"
        )

    except Exception as e:
        await message.reply(f"❌ Error: `{e}`")




@Client.on_message(filters.command("allartists"))
async def get_all_indian_artists(client, message):
    try:
        # Initialize Spotify manager
        manager = get_spotify_manager()
        manager.set_telegram_client(client)
        sp = await manager.get_spotify_client()

        queries = [
            "top hindi songs", "top bollywood", "top punjabi hits", "latest gujarati songs",
            "indian classical", "indie india", "top tamil hits", "top telugu songs",
            "top marathi tracks", "indian rap", "indian pop", "arijit singh", "shreya ghoshal",
            "regional india", "indian devotional", "desi hip hop"
        ]

        artists_dict = {}

        for query in queries:
            results = await sp.search(q=query, type='track', limit=50, market='IN')
            for item in results['tracks']['items']:
                for artist in item['artists']:
                    artists_dict[artist['name']] = f"https://open.spotify.com/artist/{artist['id']}"

        # Sorted artist list
        sorted_artists = sorted(artists_dict.items())
        total_count = len(sorted_artists)

        # Build final text
        text = f"🇮🇳 **All Indian Artist List (Auto Compiled)**\n🎧 **Total Unique Artists Found:** {total_count}\n\n"
        for idx, (name, url) in enumerate(sorted_artists, 1):
            text += f"{idx}. [{name}]({url})\n"

        # Save to .txt file (no markdown, just raw)
        plain_text = "\n".join([f"{idx}. {name} - {url}" for idx, (name, url) in enumerate(sorted_artists, 1)])
        with open("indian_artists_list.txt", "w", encoding="utf-8") as f:
            f.write(plain_text)

        await message.reply_document(
            "indian_artists_list.txt",
            caption=f"✅ Found `{total_count}` unique Indian artists via Spotify search."
        )

    except Exception as e:
        await message.reply(f"❌ Error: `{e}`")


import asyncio
import re
from pyrogram import Client, filters
from spotipy import SpotifyException



def extract_artist_id(artist_url):
    match = re.search(r"artist/([a-zA-Z0-9]+)", artist_url)
    return match.group(1) if match else None


async def safe_spotify_call(func, *args, **kwargs):
    while True:
        try:
            return func(*args, **kwargs)
        except SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 5))
                logger.warning(f"🔁 429 Error. Retrying after {retry_after}s...")
                await asyncio.sleep(retry_after + 1)
            else:
                raise

PROGRESS_FILE = "progress.json"

import os
import time
import json
import re
import asyncio


@Client.on_message(filters.command("sa") & filters.private & filters.reply)
async def artist_bulk_tracks(client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("❗ Please reply to a `.txt` file containing artist links.")
        return

    args = message.text.strip().split()
    manual_skip = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    status_msg = await message.reply("📥 Downloading file...")

    file_path = await message.reply_to_message.download()
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Initialize Spotify manager
    manager = get_spotify_manager()
    manager.set_telegram_client(client)
    sp = await manager.get_spotify_client()

    # Define helper functions to fetch album and track data
    async def get_artist_albums(artist_id):
        albums = []
        try:
            albums_response = await sp.artist_albums(artist_id, album_type='album,single,appears_on,compilation', limit=50)
            if albums_response:
                albums.extend(albums_response['items'])
                while albums_response.get('next'):
                    albums_response = await sp.next(albums_response)
                    if albums_response:
                        albums.extend(albums_response['items'])
        except Exception as e:
            logger.error(f"Error getting albums for artist {artist_id}: {e}")
            return None
        return albums

    async def get_album_tracks(album_id):
        tracks = []
        try:
            tracks_response = await sp.album_tracks(album_id, limit=50)
            if tracks_response:
                tracks.extend(tracks_response['items'])
                while tracks_response.get('next'):
                    tracks_response = await sp.next(tracks_response)
                    if tracks_response:
                        tracks.extend(tracks_response['items'])
        except Exception as e:
            logger.error(f"Error getting tracks for album {album_id}: {e}")
            return None
        return tracks

    all_tracks = []
    request_counter = 0
    start_index = 0
    last_reset = time.time()

    if manual_skip is not None:
        start_index = manual_skip
        artist_counter = start_index
        await message.reply(f"⏩ Starting from artist #{start_index+1} (manual skip).")
    elif os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as pf:
                content = pf.read().strip()
                if not content:
                    raise ValueError("Progress file is empty.")
                progress = json.loads(content)
                start_index = progress.get("artist_index", 0)
                request_counter = progress.get("request_counter", 0)
                all_tracks = progress.get("all_tracks", [])
            artist_counter = start_index
            await message.reply(f"🔄 Resuming from artist #{start_index+1} with {request_counter} requests used.")
        except Exception as e:
            await message.reply(f"⚠️ Progress file corrupted or empty. Starting fresh.\n\nError: {e}")
            start_index = 0
            request_counter = 0
            all_tracks = []
            artist_counter = 0
    else:
        await message.reply("🚀 Starting fresh...")
        artist_counter = 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"all_tracks_{timestamp}.txt"

    for idx in range(start_index, len(lines)):
        line = lines[idx].strip()
        match = re.search(r"spotify\.com/artist/([a-zA-Z0-9]+)", line)
        if not match:
            continue

        artist_id = match.group(1)
        artist_counter += 1

        await status_msg.edit(f"🎧 Processing Artist #{artist_counter}: `{artist_id}`")

        artist_tracks = []
        try:
            # Get all albums for the artist
            albums = await get_artist_albums(artist_id)

            if not albums:
                await status_msg.edit_text(f"⚠️ No albums found for artist `{artist_id}` or all clients rate-limited")
                continue

            for album in albums:
                album_id = album['id']

                # Get all tracks for this album
                tracks = await get_album_tracks(album_id)

                if not tracks:
                    continue

                for track in tracks:
                    track_id = track['id']
                    if track_id and track_id not in artist_tracks:
                        artist_tracks.append(track_id)

                # Write tracks to output file as we collect them
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write("\n".join(all_tracks + artist_tracks))

                await asyncio.sleep(0.1)  # Small delay between albums

        except Exception as e:
            logger.warning(f"⚠️ Error with artist {artist_id}: {e}")

        if artist_tracks:
            artist_info = await sp.artist(artist_id)
            artist_name = artist_info.get("name", artist_id)
            # Removed individual artist file creation, tracks are now written to the main file.
            #filename = f"artist_{artist_name}__{artist_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            #with open(filename, "w", encoding="utf-8") as f:
            #    f.write("\n".join(artist_tracks))

            #await client.send_document(
            #    chat_id=message.chat.id,
            #    document=filename,
            #    caption=f"✅ Artist #{artist_counter}: - {artist_name}__`{artist_id}` — {len(artist_tracks)} tracks"
            #)

            all_tracks.extend(artist_tracks)
            await asyncio.sleep(1)

        # Save progress
        with open(PROGRESS_FILE, "w", encoding="utf-8") as pf:
            json.dump({
                "artist_index": idx + 1,
                "request_counter": request_counter,
                "all_tracks": all_tracks
            }, pf)

        if request_counter >= 10000:
            await message.reply(f"⛔ 10,000 request limit reached. Progress saved at artist #{idx+1}.")
            os.remove(file_path)
            return

    # Send final output file
    if all_tracks:
        await client.send_document(
            chat_id=message.chat.id,
            document=output_filename,
            caption=f"🎉 **Complete Run Summary**\n"
                   f"📊 Total tracks: {len(all_tracks)}\n"
                   f"👥 Artists processed: {artist_counter}\n"
                   f"⏰ Completed at: {datetime.now().strftime('%H:%M:%S')}\n\n"
                   f"📋 Client status:\n{manager.get_client_status()}"
        )

    # Log completion to Telegram
    await manager._log_to_telegram(
        f"✅ Artist extraction completed!\n"
        f"📊 Total tracks: {len(all_tracks)}\n" 
        f"👥 Artists processed: {artist_counter}\n"
        f"📋 Final client status:\n{manager.get_client_status()}"
    )

    # Clean up
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    if os.path.exists(file_path):
        os.remove(file_path)

    await status_msg.edit("✅ Done! All artist track IDs fetched.")

@Client.on_message(filters.command("checkall") & filters.private & filters.reply)
async def check_tracks_in_db(client, message):
    if not message.reply_to_message.document:
        await message.reply("❗ Please reply to a `.txt` file containing track IDs (one per line).")
        return

    status_msg = await message.reply("📥 Downloading file and starting processing...")

    file_path = await message.reply_to_message.download()
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    total_tracks = len(lines)
    new_tracks = []
    already_in_db = 0

    for idx, track_id in enumerate(lines, 1):
        try:
            exists = await db.get_dump_file_id(track_id)
            if not exists:
                new_tracks.append(track_id)
            else:
                already_in_db += 1

            if idx % 100 == 0 or idx == total_tracks:
                text = (
                    f"Processing tracks...\n"
                    f"Total tracks: {total_tracks}\n"
                    f"Checked: {idx}\n"
                    f"Already in DB: {already_in_db}\n"
                    f"New tracks to add: {len(new_tracks)}"
                )
                try:
                    await status_msg.edit(text)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                except Exception:
                    pass

        except FloodWait as e:
            await asyncio.sleep(e.x)
            continue
        except Exception as e:
            print(f"Error checking track {track_id}: {e}")
            continue

    batch_size = 5000
    batches = [new_tracks[i:i + batch_size] for i in range(0, len(new_tracks), batch_size)]

    for i, batch in enumerate(batches, 1):
        filename = f"new_tracks_part_{i}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(batch))

        await client.send_document(
            chat_id=message.chat.id,
            document=filename,
            caption=f"✅ New Tracks Batch {i}/{len(batches)} - {len(batch)} tracks"
        )
        await asyncio.sleep(3)

    await status_msg.edit(
        f"✅ Done!\n"
        f"Total tracks in file: {total_tracks}\n"
        f"Already in DB: {already_in_db}\n"
        f"New tracks files sent: {len(batches)}"
    )