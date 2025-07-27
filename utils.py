# utils.py

# Improved file operations and error handling
import aiohttp
import asyncio
import logging
import os
import re
import urllib.parse

import random
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

def ensure_file_exists(file_path: str, default_content: Any = None):
    """Ensure a file exists, create it with default content if not"""
    try:
        if not os.path.exists(file_path):
            # Create directory if needed
            directory = os.path.dirname(file_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

            # Create file with default content
            if default_content is not None:
                with open(file_path, 'w', encoding='utf-8') as f:
                    if isinstance(default_content, (dict, list)):
                        json.dump(default_content, f, indent=2)
                    else:
                        f.write(str(default_content))
            else:
                # Create empty file
                with open(file_path, 'w', encoding='utf-8') as f:
                    pass

            logger.info(f"Created file: {file_path}")
            return True
    except Exception as e:
        logger.error(f"Failed to create file {file_path}: {e}")
        return False

    return True

def safe_read_json(file_path: str, default: Any = None) -> Any:
    """Safely read JSON file with fallback"""
    try:
        if not os.path.exists(file_path):
            return default

        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        logger.warning(f"Could not read JSON from {file_path}: {e}")
        return default
    except Exception as e:
        logger.error(f"Unexpected error reading {file_path}: {e}")
        return default

def safe_write_json(file_path: str, data: Any) -> bool:
    """Safely write JSON file with atomic operation"""
    try:
        # Ensure directory exists
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        # Write to temporary file first
        temp_file = file_path + '.tmp'
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic move
        if os.path.exists(file_path):
            os.remove(file_path)
        os.rename(temp_file, file_path)

        return True
    except Exception as e:
        logger.error(f"Failed to write JSON to {file_path}: {e}")
        # Clean up temp file
        temp_file = file_path + '.tmp'
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        return False


class temp(object):
    BANNED_USERS = []
    BANNED_CHATS = []
    ME = None
    CURRENT=int(os.environ.get("SKIP", 2))
    CANCEL = False
    MELCOW = {}
    U_NAME = None
    B_NAME = None
    SETTINGS = {}
    VERIFY = {}
    MOVIES = {}


def safe_filename(name: str) -> str:
    """Remove unsafe filesystem characters from a filename."""
    return re.sub(r'[\\/*?:"<>|]', '_', name)

import asyncio

aria2c_semaphore = asyncio.Semaphore(1)  # max 1 parallel

async def download_with_aria2c(url, output_dir, filename):
    async with aria2c_semaphore:
        # optional small delay before starting
        await asyncio.sleep(1)

        cmd = [
            "aria2c",
            "-x", "2",
            "-s", "2",
            "-k", "1M",
            "--max-tries=5",
            "--retry-wait=5",
            "--timeout=60",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "-d", output_dir,
            "-o", filename,
            url
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()


        if process.returncode == 0:

            return True
        else:
            logger.error(f"aria2c failed with exit code {process.returncode}")
            # optionally implement exponential backoff retry here
            return False


logger = logging.getLogger(__name__)

async def get_song_download_url_by_spotify_url(spotify_url: str):
    logger.info(f"Processing Spotify URL: {spotify_url}")
    api_urls = [
        f"https://tet-kpy4.onrender.com/spotify?url={spotify_url}",
        f"https://tet-kpy4.onrender.com/spotify2?url={spotify_url}"
    ]

    random.shuffle(api_urls)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        for api in api_urls:
            for attempt in range(3):  # Try 3 times per API
                try:
                    logger.info(f"Attempting API {api} (attempt {attempt+1})")
                    async with session.get(api) as resp:
                        if resp.status == 200:
                            try:
                                data = await resp.json()
                                if data.get("status") and "data" in data:
                                    song_data = data["data"]
                                    found_title = song_data.get("title")
                                    download_url = song_data.get("download")

                                    if download_url:
                                        logger.info(f"Successfully got download URL for: {found_title}")
                                        return found_title, download_url
                                    else:
                                        logger.warning(f"No download URL in response from {api}")
                                else:
                                    logger.warning(f"Invalid response data from {api}: {data}")
                            except (json.JSONDecodeError, KeyError) as e:
                                logger.error(f"Failed to parse JSON response from {api}: {e}")
                        else:
                            logger.error(f"API request failed with status {resp.status} from {api}")
                            error_text = await resp.text()
                            logger.error(f"Error response: {error_text[:200]}...")

                except asyncio.TimeoutError:
                    logger.error(f"Timeout while requesting {api} (attempt {attempt+1})")
                except Exception as e:
                    logger.error(f"Exception while requesting {api} (attempt {attempt+1}): {e}")

                # Small delay before retrying
                if attempt < 2:  # Don't delay after last attempt
                    await asyncio.sleep(2 + attempt)  # Progressive delay

            logger.warning(f"Failed all 3 attempts on {api}, moving to next API")

    logger.error(f"All APIs failed for URL: {spotify_url}")
    return None, None

async def download_thumbnail(thumb_url: str, output_path: str) -> bool:
    if not thumb_url:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(thumb_url) as resp:
                if resp.status == 200:
                    with open(output_path, "wb") as f:
                        f.write(await resp.read())
                    logging.info(f"Thumbnail downloaded to {output_path}")
                    return True
    except Exception as e:
        logging.error(f"Thumbnail download failed: {e}")

    return False