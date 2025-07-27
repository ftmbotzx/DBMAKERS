from pyrogram import Client, filters
import os
from database.db import db
import asyncio

COMBINED_FILE = "combined_track_ids.txt"

# 1. Auto combine track IDs when a .txt file is sent
@Client.on_message(filters.document & filters.private)
async def auto_combine_track_ids(client, message):
    if not message.document.file_name.endswith(".txt"):
        return
 
    file_path = await message.download()
    added_ids = 0

    try:
        with open(file_path, "r", encoding="utf-8") as incoming_file:
            incoming_ids = [line.strip() for line in incoming_file if line.strip()]

        # Create file if not exists
        if not os.path.exists(COMBINED_FILE):
            open(COMBINED_FILE, "w", encoding="utf-8").close()

        # Append all incoming IDs without duplicate check
        with open(COMBINED_FILE, "a", encoding="utf-8") as combined_file:
            for track_id in incoming_ids:
                combined_file.write(track_id + "\n")
                added_ids += 1

        await message.reply(f"✅ `{added_ids}` track IDs added (including duplicates).")
    except Exception as e:
        await message.reply(f"❌ Error:\n`{e}`")

# 2. /clear command to wipe the combined file
@Client.on_message(filters.command("clear") & filters.private)
async def clear_combined_file(client, message):
    if os.path.exists(COMBINED_FILE):
        open(COMBINED_FILE, "w", encoding="utf-8").close()
        await message.reply("🧹 Combined track list cleared.")
    else:
        await message.reply("⚠️ No file to clear.")


# 3. Optional: Send the combined file on demand
@Client.on_message(filters.command("getfile") & filters.private)
async def send_combined_file(client, message):
    if os.path.exists(COMBINED_FILE):
        await message.reply_document(COMBINED_FILE, caption="📄 Combined Track IDs")
    else:
        await message.reply("⚠️ No combined file found yet.")


@Client.on_message(filters.command("checkall") & filters.private & filters.reply)
async def check_tracks_in_db(client, message):
    if not message.reply_to_message.document:
        return await message.reply("❗ Please reply to a `.txt` file containing track IDs (one per line).")

    status_msg = await message.reply("📥 Downloading file and fetching DB data...")

    file_path = await message.reply_to_message.download()
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    
    total_tracks = len(lines)


    existing_tracks = set()
    async for doc in db.dump_col.find({}, {"track_id": 1, "_id": 0}):
        existing_tracks.add(doc["track_id"])

    # 🔍 Step 2: Check each track against existing set
    new_tracks = []
    already_in_db = 0

    for idx, track_id in enumerate(lines, 1):
        if track_id not in existing_tracks:
            new_tracks.append(track_id)
        else:
            already_in_db += 1

        if idx % 10000 == 0 or idx == total_tracks:
            text = (
                f"🔎 Checking tracks...\n"
                f"Total: {total_tracks}\n"
                f"Checked: {idx}\n"
                f"Already in DB: {already_in_db}\n"
                f"New Tracks: {len(new_tracks)}"
            )
            try:
                await status_msg.edit(text)
            except Exception:
                pass

    # ✍️ Step 3: Split and send new tracks in batches
    if not new_tracks:
        return await status_msg.edit("✅ Done! All tracks already exist in DB.")

    batch_size = 10000000
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
        await asyncio.sleep(2)

    await status_msg.edit(
        f"✅ Completed!\n"
        f"Total tracks: {total_tracks}\n"
        f"Already in DB: {already_in_db}\n"
        f"New tracks files sent: {len(batches)}"
    )

