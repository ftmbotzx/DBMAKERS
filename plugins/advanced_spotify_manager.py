import json
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import aiohttp
import base64
from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)

class AdvancedSpotifyManager:
    def __init__(self, clients_file: str, log_channel_id: int):
        self.clients_file = clients_file
        self.log_channel_id = log_channel_id
        self.clients = []
        self.client_stats = {}
        self.current_client_index = 0
        self.lock = asyncio.Lock()
        self.telegram_client = None
        self.token_cache_file = "token_cache.json"

        # Load clients from JSON
        self._load_clients()
        # Load cached tokens
        self._load_token_cache()

    def _load_clients(self):
        """Load client credentials from JSON file"""
        try:
            with open(self.clients_file, 'r') as f:
                data = json.load(f)
                self.clients = data.get('clients', [])

            # Initialize stats for each client
            for i, client in enumerate(self.clients):
                client_id = client['client_id']
                self.client_stats[client_id] = {
                    'requests': 0,
                    'status': 'active',  # active, rate_limited
                    'token': None,
                    'token_expiry': 0,
                    'last_used': None
                }

            logger.info(f"Loaded {len(self.clients)} Spotify clients")

        except Exception as e:
            logger.error(f"Failed to load clients from {self.clients_file}: {e}")
            self.clients = []

    def _load_token_cache(self):
        """Load cached tokens from file"""
        try:
            import os
            if not os.path.exists(self.token_cache_file):
                logger.info("Token cache file does not exist, creating new one")
                return

            # Check file permissions
            if not os.access(self.token_cache_file, os.R_OK):
                logger.error(f"Cannot read token cache file: {self.token_cache_file}")
                return

            with open(self.token_cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            loaded_count = 0
            for client_id, cache_info in cache_data.items():
                if client_id in self.client_stats:
                    # Only load if not expired and valid
                    expiry_time = cache_info.get('token_expiry', 0)
                    if time.time() < expiry_time and cache_info.get('token'):
                        self.client_stats[client_id]['token'] = cache_info.get('token')
                        self.client_stats[client_id]['token_expiry'] = expiry_time
                        loaded_count += 1
                        logger.info(f"Loaded cached token for client {client_id[:8]}...")

            if loaded_count > 0:
                logger.info(f"Successfully loaded {loaded_count} cached tokens")

        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.info(f"Could not load token cache (file issue): {e}")
        except PermissionError as e:
            logger.error(f"Permission denied reading token cache: {e}")
        except Exception as e:
            logger.error(f"Unexpected error loading token cache: {e}")

    def _save_token_cache(self):
        """Save tokens to cache file"""
        try:
            import os
            cache_data = {}
            current_time = time.time()
            
            for client_id, stats in self.client_stats.items():
                token = stats.get('token')
                expiry = stats.get('token_expiry', 0)
                
                # Only save valid, non-expired tokens
                if token and expiry > current_time:
                    cache_data[client_id] = {
                        'token': token,
                        'token_expiry': expiry
                    }

            # Create directory if needed
            cache_dir = os.path.dirname(self.token_cache_file)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)

            # Write with proper encoding and atomic operation
            temp_file = self.token_cache_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            # Atomic move
            if os.path.exists(self.token_cache_file):
                os.remove(self.token_cache_file)
            os.rename(temp_file, self.token_cache_file)
            
            logger.info(f"Saved {len(cache_data)} tokens to cache")

        except PermissionError as e:
            logger.error(f"Permission denied writing token cache: {e}")
        except OSError as e:
            logger.error(f"OS error saving token cache: {e}")
        except Exception as e:
            logger.error(f"Unexpected error saving token cache: {e}")

    def set_telegram_client(self, telegram_client):
        """Set the Telegram client for logging"""
        self.telegram_client = telegram_client

    async def _log_to_telegram(self, message: str):
        """Send log message to Telegram channel"""
        if self.telegram_client and self.log_channel_id:
            try:
                await self.telegram_client.send_message(
                    chat_id=self.log_channel_id,
                    text=f"🔄 **Spotify Manager**\n\n{message}"
                )
            except Exception as e:
                logger.error(f"Failed to send Telegram log: {e}")

    async def _get_access_token(self, client_id: str, client_secret: str) -> Optional[str]:
        """Get access token for a specific client"""
        try:
            auth_string = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers = {
                'Authorization': f'Basic {auth_string}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {'grant_type': 'client_credentials'}

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://accounts.spotify.com/api/token',
                    headers=headers,
                    data=data
                ) as response:
                    if response.status == 200:
                        token_data = await response.json()
                        return token_data.get('access_token')
                    elif response.status == 429:
                        # Mark as rate limited
                        self.client_stats[client_id]['status'] = 'rate_limited'
                        await self._log_to_telegram(f"❌ Client `{client_id[:8]}...` rate limited during token fetch")
                        return None
                    elif response.status in [400, 401]:
                        # Mark as invalid credentials
                        self.client_stats[client_id]['status'] = 'invalid'
                        await self._log_to_telegram(f"❌ Client `{client_id[:8]}...` has invalid credentials")
                        logger.error(f"Invalid credentials for client {client_id[:8]}...")
                        return None
                    else:
                        logger.error(f"Token request failed: {response.status}")
                        error_text = await response.text()
                        logger.error(f"Response: {error_text}")
                        return None
        except Exception as e:
            logger.error(f"Error getting token for {client_id[:8]}...: {e}")
            return None

    async def get_spotify_client(self):
        """Get current Spotify client with aggressive rotation and error recovery"""
        async with self.lock:
            if not self.clients:
                raise Exception("No Spotify clients available")

            max_attempts = len(self.clients) + 2
            current_attempt = 0

            while current_attempt < max_attempts:
                current_attempt += 1
                
                # Get current client
                if self.current_client_index >= len(self.clients):
                    self.current_client_index = 0
                    
                current_client = self.clients[self.current_client_index]
                client_id = current_client['client_id']
                client_secret = current_client['client_secret']
                stats = self.client_stats[client_id]

                # Skip invalid clients immediately
                if stats['status'] == 'invalid':
                    await self._switch_to_next_client()
                    continue

                # Check if we need a new token
                current_time = time.time()
                token_buffer = 300  # 5 minute buffer before expiry
                
                needs_new_token = (
                    not stats.get('token') or 
                    current_time >= (stats.get('token_expiry', 0) - token_buffer) or 
                    stats['status'] == 'rate_limited'
                )

                if needs_new_token:
                    logger.info(f"Getting new token for client {client_id[:8]}...")
                    token = await self._get_access_token(client_id, client_secret)
                    
                    if token:
                        stats['token'] = token
                        stats['token_expiry'] = current_time + 3600  # 1 hour
                        stats['status'] = 'active'
                        stats['last_used'] = datetime.now()
                        
                        # Save to cache asynchronously to avoid blocking
                        try:
                            self._save_token_cache()
                        except Exception as e:
                            logger.warning(f"Failed to save token cache: {e}")
                        
                        logger.info(f"Successfully got token for client {client_id[:8]}...")
                        return SpotifyClientWrapper(self, client_id)
                    else:
                        # Token failed, mark client and try next
                        logger.warning(f"Failed to get token for client {client_id[:8]}...")
                        if stats['status'] != 'rate_limited':
                            stats['status'] = 'rate_limited'
                        
                        await self._switch_to_next_client()
                        continue
                else:
                    # Token is still valid
                    stats['last_used'] = datetime.now()
                    return SpotifyClientWrapper(self, client_id)

            # If we get here, all attempts failed
            raise Exception(f"Unable to get working Spotify client after {max_attempts} attempts")

    async def _switch_to_next_client(self):
        """Switch to the next available client with improved logic"""
        if not self.clients:
            return False

        original_index = self.current_client_index
        attempts = 0
        max_attempts = len(self.clients) * 2  # Allow multiple rounds

        # First pass: Look for immediately available clients
        for _ in range(len(self.clients)):
            attempts += 1
            self.current_client_index = (self.current_client_index + 1) % len(self.clients)
            client = self.clients[self.current_client_index]
            client_id = client['client_id']
            stats = self.client_stats[client_id]

            # Check if client is available and has a valid token
            if stats['status'] == 'active':
                # Additional check: ensure token is still valid
                if (stats.get('token') and 
                    stats.get('token_expiry', 0) > time.time() + 300):  # 5 min buffer
                    await self._log_to_telegram(f"🔄 Switched to client `{client_id[:8]}...`")
                    logger.info(f"Switched to active client {client_id[:8]}...")
                    return True

        # Second pass: Try to revive rate-limited clients (they might be ready now)
        current_time = time.time()
        for client_id, stats in self.client_stats.items():
            if stats['status'] == 'rate_limited':
                # Give rate-limited clients another chance after some time
                last_used = stats.get('last_used')
                if (not last_used or 
                    (isinstance(last_used, datetime) and 
                     (datetime.now() - last_used).total_seconds() > 60)):
                    
                    stats['status'] = 'active'
                    stats['token'] = None  # Force token refresh
                    stats['token_expiry'] = 0
                    
                    # Find and switch to this client
                    for i, client in enumerate(self.clients):
                        if client['client_id'] == client_id:
                            self.current_client_index = i
                            await self._log_to_telegram(f"🔄 Retrying client `{client_id[:8]}...` after cooldown")
                            logger.info(f"Retrying rate-limited client {client_id[:8]}...")
                            return True

        # Check available client status
        active_clients = [cid for cid, stats in self.client_stats.items() 
                         if stats['status'] == 'active']
        rate_limited_clients = [cid for cid, stats in self.client_stats.items() 
                               if stats['status'] == 'rate_limited']
        invalid_clients = [cid for cid, stats in self.client_stats.items() 
                          if stats['status'] == 'invalid']

        if not active_clients and not rate_limited_clients:
            await self._log_to_telegram("❌ All clients are invalid. Please check credentials.")
            logger.error("No valid clients available")
            return False
        elif not active_clients:
            await self._log_to_telegram("⚠️ All clients rate-limited. Will retry with delays.")
            logger.warning("All clients are rate-limited")
            # Force retry the first rate-limited client
            if rate_limited_clients:
                first_client = rate_limited_clients[0]
                self.client_stats[first_client]['status'] = 'active'
                for i, client in enumerate(self.clients):
                    if client['client_id'] == first_client:
                        self.current_client_index = i
                        return True

        return len(active_clients) > 0 or len(rate_limited_clients) > 0

    async def switch_to_client(self, target_client_id: str) -> bool:
        """Manually switch to a specific client"""
        async with self.lock:
            for i, client in enumerate(self.clients):
                if client['client_id'] == target_client_id:
                    if self.client_stats[target_client_id]['status'] == 'active':
                        self.current_client_index = i
                        await self._log_to_telegram(f"🔄 Manually switched to client `{target_client_id[:8]}...`")
                        return True
                    else:
                        return False
            return False

    def get_client_status(self):
        """Get formatted status of all clients"""
        status_lines = []
        for client_id, stats in self.client_stats.items():
            short_id = client_id[:8]

            if stats['status'] == 'active':
                emoji = "🟢"
                status_text = f"{stats['requests']} requests"
            elif stats['status'] == 'rate_limited':
                emoji = "🔴"
                status_text = "rate-limited"
            elif stats['status'] == 'invalid':
                emoji = "❌"
                status_text = "invalid credentials"
            else:
                emoji = "❓"
                status_text = f"unknown ({stats['status']})"

            status_lines.append(f"{emoji} `{short_id}` – {status_text}")

        return '\n'.join(status_lines) if status_lines else "❌ No clients loaded"

    def get_current_client_id(self):
        """Get the current active client ID"""
        if self.clients and self.current_client_index < len(self.clients):
            return self.clients[self.current_client_index]['client_id']
        return "None"

class SpotifyClientWrapper:
    """Wrapper to track requests and handle rate limits"""

    def __init__(self, manager: AdvancedSpotifyManager, client_id: str):
        self.manager = manager
        self.client_id = client_id
        self.request_count = 0
        self.last_request_time = 0
        self.min_request_interval = 0.1  # 100ms between requests

    async def _make_request(self, url: str, params: dict = None, retry_count: int = 0):
        """Make authenticated request to Spotify API with improved error handling"""
        if retry_count > 5:  # Increased max retries
            logger.error(f"Max retries ({retry_count}) exceeded for URL: {url}")
            return None

        stats = self.manager.client_stats[self.client_id]
        token = stats.get('token')
        
        if not token:
            logger.error(f"No token available for client {self.client_id[:8]}...")
            return None

        headers = {
            'Authorization': f'Bearer {token}',
            'User-Agent': 'SpotifyBot/1.0'
        }

        try:
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, params=params) as response:
                    stats['requests'] = stats.get('requests', 0) + 1

                    if response.status == 429:
                        # Rate limited - immediate client switch
                        retry_after = int(response.headers.get('Retry-After', 60))
                        stats['status'] = 'rate_limited'
                        
                        logger.warning(f"Rate limit hit for client {self.client_id[:8]}... (retry {retry_count + 1})")
                        
                        # Aggressive client switching
                        switch_success = await self.manager._switch_to_next_client()
                        if switch_success:
                            # Small delay then retry with new client
                            await asyncio.sleep(0.2)
                            new_client = await self.manager.get_spotify_client()
                            return await new_client._make_request(url, params, retry_count + 1)
                        else:
                            # All clients rate limited, wait minimal time
                            wait_time = min(retry_after, 5)
                            logger.info(f"All clients rate limited, waiting {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            return await self._make_request(url, params, retry_count + 1)

                    elif response.status == 401:
                        # Token expired - force refresh
                        logger.info(f"Token expired for client {self.client_id[:8]}..., refreshing")
                        stats['token'] = None
                        stats['token_expiry'] = 0
                        
                        # Get fresh client and retry immediately
                        new_client = await self.manager.get_spotify_client()
                        return await new_client._make_request(url, params, retry_count + 1)

                    elif response.status == 200:
                        # Success - update stats
                        stats['last_used'] = datetime.now()
                        return await response.json()
                        
                    elif response.status == 404:
                        # Not found - don't retry
                        logger.warning(f"Resource not found: {url}")
                        return None
                        
                    elif response.status >= 500:
                        # Server error - try different client
                        logger.warning(f"Server error {response.status} for client {self.client_id[:8]}...")
                        await self.manager._switch_to_next_client()
                        new_client = await self.manager.get_spotify_client()
                        await asyncio.sleep(0.5)  # Brief delay for server errors
                        return await new_client._make_request(url, params, retry_count + 1)
                        
                    else:
                        # Other errors
                        error_text = await response.text()
                        logger.error(f"API error {response.status} for client {self.client_id[:8]}...: {error_text}")
                        
                        # Try switching client for client errors too
                        if retry_count < 3:
                            await self.manager._switch_to_next_client()
                            new_client = await self.manager.get_spotify_client()
                            return await new_client._make_request(url, params, retry_count + 1)
                        
                        return None

        except asyncio.TimeoutError:
            logger.warning(f"Timeout for client {self.client_id[:8]}... (retry {retry_count + 1})")
            # Try different client on timeout
            await self.manager._switch_to_next_client()
            new_client = await self.manager.get_spotify_client()
            return await new_client._make_request(url, params, retry_count + 1)

        except aiohttp.ClientError as e:
            logger.error(f"Client error for {self.client_id[:8]}...: {e}")
            # Try different client on connection errors
            if retry_count < 3:
                await self.manager._switch_to_next_client()
                new_client = await self.manager.get_spotify_client()
                await asyncio.sleep(1)
                return await new_client._make_request(url, params, retry_count + 1)
            return None

        except Exception as e:
            logger.error(f"Unexpected error for client {self.client_id[:8]}...: {e}")
            return None

    async def _rate_limit_delay(self):
        """Smart delay between requests to avoid rate limits"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            delay = self.min_request_interval - time_since_last
            await asyncio.sleep(delay)
        
        self.last_request_time = time.time()
        self.request_count += 1
        
        # Progressive delays for high request counts
        if self.request_count > 50:
            await asyncio.sleep(0.2)
        elif self.request_count > 100:
            await asyncio.sleep(0.5)

    # Spotify API methods with rate limiting
    async def user_playlists(self, user_id: str, limit: int = 50):
        await self._rate_limit_delay()
        url = f"https://api.spotify.com/v1/users/{user_id}/playlists"
        params = {'limit': limit}
        return await self._make_request(url, params)

    async def playlist_tracks(self, playlist_id: str, limit: int = 50, offset: int = 0):
        await self._rate_limit_delay()
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        params = {'limit': limit, 'offset': offset}
        return await self._make_request(url, params)

    async def artist_albums(self, artist_id: str, album_type: str = 'album', limit: int = 50, offset: int = 0):
        await self._rate_limit_delay()
        url = f"https://api.spotify.com/v1/artists/{artist_id}/albums"
        params = {'album_type': album_type, 'limit': limit, 'offset': offset}
        return await self._make_request(url, params)

    async def album_tracks(self, album_id: str, limit: int = 50, offset: int = 0):
        await self._rate_limit_delay()
        url = f"https://api.spotify.com/v1/albums/{album_id}/tracks"
        params = {'limit': limit, 'offset': offset}
        return await self._make_request(url, params)

    async def next(self, result: dict):
        """Handle pagination with rate limiting"""
        if result and result.get('next'):
            await self._rate_limit_delay()
            return await self._make_request(result['next'])
        return None

# Global manager instance
spotify_manager = None

def get_spotify_manager():
    global spotify_manager
    if not spotify_manager:
        from info import LOG_CHANNEL
        spotify_manager = AdvancedSpotifyManager("clients.json", LOG_CHANNEL)
    return spotify_manager

@Client.on_message(filters.command("working") & filters.private)
async def show_client_status(client: Client, message: Message):
    """Show current status of all Spotify clients"""
    manager = get_spotify_manager()
    manager.set_telegram_client(client)

    status = manager.get_client_status()
    current_client = manager.get_current_client_id()

    response = f"📊 **Spotify Clients Status**\n\n{status}\n\n🎯 **Current Active:** `{current_client[:8] if current_client != 'None' else 'None'}`"
    response += f"\n\n💡 Use `/monitor` for real-time testing"
    await message.reply(response)

@Client.on_message(filters.command("switch") & filters.private)
async def switch_client(client: Client, message: Message):
    """Manually switch to a specific client"""
    if len(message.command) < 2:
        await message.reply("❗ Usage: `/switch <client_id>`")
        return

    target_client_id = message.command[1]
    manager = get_spotify_manager()
    manager.set_telegram_client(client)

    success = await manager.switch_to_client(target_client_id)

    if success:
        await message.reply(f"✅ Switched to client: `{target_client_id}`")
    else:
        await message.reply(f"❌ Cannot switch to `{target_client_id}` (not found or rate-limited)")