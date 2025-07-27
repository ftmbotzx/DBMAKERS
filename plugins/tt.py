# plugins/check_clients.py

from pyrogram import Client, filters
from pyrogram.types import Message
import aiohttp
import base64
import asyncio

client_credentials = [
    ("5561376fd0234838863a8c3a6cbb0865", "fa12e995f56c48a28e28fb056e041d18"),
    ("a8c78174e7524e109d669ee67bbad3f2", "3074289c88ac4071bef5c11ca210a8e5"),

]

async def check_credentials(session, client_id, client_secret):
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "client_credentials"}

    try:
        async with session.post("https://accounts.spotify.com/api/token", headers=headers, data=data) as resp:
            status = resp.status
            if status == 200:
                return f"✅ `{client_id}` — Working"
            elif status == 429:
                return f"⚠️ `{client_id}` — Rate Limited"
            elif status in [400, 401]:
                return f"❌ `{client_id}` — Invalid"
            else:
                return f"❓ `{client_id}` — Unknown Error ({status})"
    except Exception as e:
        return f"❌ `{client_id}` — Error: {e}"

@Client.on_message(filters.command("test") & filters.private)
async def check_spotify_clients(_, message: Message):
    status_msg = await message.reply("🔍 Checking all Spotify client credentials...")

    async with aiohttp.ClientSession() as session:
        tasks = [
            check_credentials(session, cid, secret)
            for cid, secret in client_credentials
        ]
        results = await asyncio.gather(*tasks)

    result_text = "\n".join(results)

    if len(result_text) > 4096:
        result_text = result_text[:4090] + "\n\n⚠️ Output truncated..."

    await status_msg.edit_text(f"🔎 **Spotify Client Check Result:**\n\n{result_text}")
