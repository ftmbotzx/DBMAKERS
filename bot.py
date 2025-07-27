import os
import logging
import asyncio
import importlib
from collections import deque
from asyncio import Queue
import random
import uuid
import re
from typing import Union, Optional, AsyncGenerator
import pytz
from datetime import date, datetime
from aiohttp import web
from pyrogram import Client, __version__, filters, types, utils as pyroutils
from pyrogram.raw.all import layer

from plugins import web_server
from info import SESSION, API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL, PORT, USER_SESSION, ADMINS

from typing import AsyncGenerator, Union
from pyrogram.types import Message

# Logging setup
logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# Adjust Pyrogram chat ID ranges
pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -100999999999999



# ------------------ Bot Class ------------------ #
class Bot(Client):
    def __init__(self):
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=1000,
            plugins={"root": "plugins"},
            sleep_threshold=10, 
            max_concurrent_transmissions=6
        )

    async def start(self):
        await super().start()
        me = await self.get_me()
        logging.info(f"🤖 {me.first_name} (@{me.username}) running on Pyrogram v{__version__} (Layer {layer})")
       
        # Initialize Spotify manager
        from plugins.advanced_spotify_manager import get_spotify_manager
        spotify_manager = get_spotify_manager()
        spotify_manager.set_telegram_client(self)
        await spotify_manager._log_to_telegram("🚀 Spotify Manager initialized with client rotation system")
        
        tz = pytz.timezone('Asia/Kolkata')
        today = date.today()
        now = datetime.now(tz)
        time = now.strftime("%H:%M:%S %p")
        await self.send_message(chat_id=LOG_CHANNEL, text=f"✅ Bot Restarted! 📅 Date: {today} 🕒 Time: {time}")
        app = web.AppRunner(await web_server())
        await app.setup()
        await web.TCPSite(app, "0.0.0.0", PORT).start()
        logging.info(f"🌐 Web Server Running on PORT {PORT}")
        

    async def iter_messages(
        self,
        chat_id: Union[int, str],
        limit: int = 100,
        offset_id: int = 0
    ) -> AsyncGenerator[Message, None]:
        total = 0
        current_id = offset_id if offset_id > 0 else (await self.get_history(chat_id, limit=1))[0].id

        while total < limit:
            batch_limit = min(100, limit - total)

            # Generate list of message IDs decreasing from current_id backwards
            message_ids = list(range(current_id, current_id - batch_limit, -1))
            if not message_ids:
                break

            messages = await self.get_messages(chat_id, message_ids)

            if not messages:
                break

            for message in messages:
                yield message
                total += 1
                current_id = message.id - 1
                if total >= limit:
                    break

            if len(messages) < batch_limit:
                break
                

    async def stop(self, *args):
        await super().stop()
        logging.info("🛑 Bot Stopped.")

app = Bot()
app.run()

