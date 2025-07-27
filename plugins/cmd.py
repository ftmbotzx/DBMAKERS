from pyrogram import Client, filters
import os
import time
import logging 
import aiohttp
import requests
import asyncio
import subprocess
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import LOG_CHANNEL, ADMINS, BOT_TOKEN
from pyrogram.types import Message
from pyrogram.enums import ChatType
from database.db import db 


@Client.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 Hello! Bot is running successfully!")


@Client.on_message(filters.command("restart"))
async def git_pull(client, message):
    if message.from_user.id not in ADMINS:
        return await message.reply_text("🚫 **You are not authorized to use this command!**")
      
    working_directory = "/home/ubuntu/DBMAKKER"

    process = subprocess.Popen(
        "git pull https://github.com/Anshvachhani998/DBMAKKER",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE

    )

    stdout, stderr = process.communicate()
    output = stdout.decode().strip()
    error = stderr.decode().strip()
    cwd = os.getcwd()
    logging.info("Raw Output (stdout): %s", output)
    logging.info("Raw Error (stderr): %s", error)

    if error and "Already up to date." not in output and "FETCH_HEAD" not in error:
        await message.reply_text(f"❌ Error occurred: {os.getcwd()}\n{error}")
        logging.info(f"get dic {cwd}")
        return

    if "Already up to date." in output:
        await message.reply_text("🚀 Repository is already up to date!")
        return
      
    if any(word in output.lower() for word in [
        "updating", "changed", "insert", "delete", "merge", "fast-forward",
        "files", "create mode", "rename", "pulling"
    ]):
        await message.reply_text(f"📦 Git Pull Output:\n```\n{output}\n```")
        await message.reply_text("🔄 Git Pull successful!\n♻ Restarting bot...")

        subprocess.Popen("bash /home/ubuntu/DBMAKKER/start.sh", shell=True)
        os._exit(0)

    await message.reply_text(f"📦 Git Pull Output:\n```\n{output}\n```")


@Client.on_message(filters.command("dbcheck") & filters.user(ADMINS))
async def dbcheck_handler(client: Client, message: Message):
    try:
        # Total media documents
        media_count = await db.db["media"].count_documents({})

        # Total dump documents
        dump_count = await db.db["dump"].count_documents({})

        # Aapke other collections bhi ho toh unka yahan add karo:
        # example: user_count = await db.db["users"].count_documents({})

        text = (
            f"📊 **Database Stats:**\n\n"
            f"📁 Media Files: `{media_count}`\n"
            f"🗃️ Dump Entries: `{dump_count}`\n"
            # f"👤 Users: `{user_count}`\n"  # Add if needed
        )
        await message.reply(text)

    except Exception as e:
        await message.reply(f"❌ Error occurred: `{e}`")


@Client.on_message(filters.command("deleteall"))
async def delete_all_media(client, message):
    result = await db.media_col.delete_many({})
    await message.reply(f"🗑️ Deleted **{result.deleted_count}** entries from media DB.")
