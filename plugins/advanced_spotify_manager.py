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
            with open(self.token_cache_file, 'r') as f:
                cache_data = json.load(f)
                
            for client_id, cache_info in cache_data.items():
                if client_id in self.client_stats:
                    # Only load if not expired
                    if time.time() < cache_info.get('token_expiry', 0):
                        self.client_stats[client_id]['token'] = cache_info.get('token')
                        self.client_stats[client_id]['token_expiry'] = cache_info.get('token_expiry')
                        logger.info(f"Loaded cached token for client {client_id[:8]}...")
                        
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            logger.info(f"Could not load token cache: {e}")

    def _save_token_cache(self):
        """Save tokens to cache file"""
        try:
            cache_data = {}
            for client_id, stats in self.client_stats.items():
                if stats.get('token') and stats.get('token_expiry', 0) > time.time():
                    cache_data[client_id] = {
                        'token': stats['token'],
                        'token_expiry': stats['token_expiry']
                    }
            
            with open(self.token_cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Could not save token cache: {e}")

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
        """Get current Spotify client with automatic rotation on rate limits"""
        async with self.lock:
            if not self.clients:
                raise Exception("No Spotify clients available")

            # Try current client first
            current_client = self.clients[self.current_client_index]
            client_id = current_client['client_id']
            client_secret = current_client['client_secret']

            # Check if we need a new token
            stats = self.client_stats[client_id]
            if (not stats['token'] or 
                time.time() >= stats['token_expiry'] or 
                stats['status'] == 'rate_limited'):

                token = await self._get_access_token(client_id, client_secret)
                if token:
                    stats['token'] = token
                    stats['token_expiry'] = time.time() + 3600  # 1 hour
                    stats['status'] = 'active'
                    stats['last_used'] = datetime.now()
                    # Save to cache
                    self._save_token_cache()
                else:
                    # Try to switch to next client
                    await self._switch_to_next_client()
                    return await self.get_spotify_client()

            return SpotifyClientWrapper(self, client_id)

    async def _switch_to_next_client(self):
        """Switch to the next available client"""
        original_index = self.current_client_index
        attempts = 0
        
        # First, try to find an immediately available client
        for _ in range(len(self.clients)):
            attempts += 1
            self.current_client_index = (self.current_client_index + 1) % len(self.clients)
            client = self.clients[self.current_client_index]
            client_id = client['client_id']

            # Check if client is available (not rate limited or invalid)
            stats = self.client_stats[client_id]
            if stats['status'] == 'active':
                await self._log_to_telegram(f"🔄 Switched to client `{client_id[:8]}...` (attempt {attempts})")
                logger.info(f"Switched to client {client_id[:8]}... after {attempts} attempts")
                return True

        # If no immediately available clients, try to reset rate-limited ones after some time
        rate_limited_clients = [cid for cid, stats in self.client_stats.items() 
                               if stats['status'] == 'rate_limited']
        
        if rate_limited_clients:
            # Reset the first rate-limited client to give it another chance
            first_rate_limited = rate_limited_clients[0]
            self.client_stats[first_rate_limited]['status'] = 'active'
            
            # Find and switch to this client
            for i, client in enumerate(self.clients):
                if client['client_id'] == first_rate_limited:
                    self.current_client_index = i
                    await self._log_to_telegram(f"🔄 Retrying rate-limited client `{first_rate_limited[:8]}...`")
                    return True

        # Check if we have any valid clients left
        valid_clients = [cid for cid, stats in self.client_stats.items() 
                        if stats['status'] not in ['invalid']]

        if not valid_clients:
            await self._log_to_telegram("❌ All clients are invalid. Please check credentials.")
        else:
            await self._log_to_telegram("⚠️ All clients temporarily rate-limited. Retrying in rotation.")

        return len(valid_clients) > 0

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

    async def _make_request(self, url: str, params: dict = None, retry_count: int = 0):
        """Make authenticated request to Spotify API"""
        if retry_count > 3:  # Maximum 3 retries
            logger.error(f"Max retries exceeded for URL: {url}")
            return None

        stats = self.manager.client_stats[self.client_id]
        token = stats['token']

        headers = {'Authorization': f'Bearer {token}'}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    stats['requests'] += 1

                    if response.status == 429:
                        # Rate limited - switch client
                        retry_after = int(response.headers.get('Retry-After', 30))
                        stats['status'] = 'rate_limited'
                        await self.manager._log_to_telegram(f"❌ Client `{self.client_id[:8]}...` hit rate limit (retry {retry_count + 1})")

                        # Immediate client switch without waiting
                        switch_success = await self.manager._switch_to_next_client()
                        if switch_success:
                            # Get new client and retry
                            new_client = await self.manager.get_spotify_client()
                            return await new_client._make_request(url, params, retry_count + 1)
                        else:
                            # Wait a bit and retry with same client
                            await asyncio.sleep(min(retry_after, 5))
                            return await self._make_request(url, params, retry_count + 1)
                    
                    elif response.status == 401:
                        # Token expired, get new token
                        await self.manager._log_to_telegram(f"🔄 Token expired for `{self.client_id[:8]}...`, refreshing")
                        stats['token'] = None
                        stats['token_expiry'] = 0
                        
                        # Get fresh client and retry
                        new_client = await self.manager.get_spotify_client()
                        return await new_client._make_request(url, params, retry_count + 1)
                    
                    elif response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Spotify API error {response.status} for client {self.client_id[:8]}...")
                        error_text = await response.text()
                        logger.error(f"Response: {error_text}")
                        
                        # Try switching client for server errors
                        if response.status >= 500:
                            await self.manager._switch_to_next_client()
                            new_client = await self.manager.get_spotify_client()
                            return await new_client._make_request(url, params, retry_count + 1)
                        
                        return None
        
        except asyncio.TimeoutError:
            logger.error(f"Timeout for client {self.client_id[:8]}...")
            # Try switching client on timeout
            await self.manager._switch_to_next_client()
            new_client = await self.manager.get_spotify_client()
            return await new_client._make_request(url, params, retry_count + 1)
        
        except Exception as e:
            logger.error(f"Request error for client {self.client_id[:8]}...: {e}")
            return None

    # Spotify API methods
    async def user_playlists(self, user_id: str):
        url = f"https://api.spotify.com/v1/users/{user_id}/playlists"
        return await self._make_request(url)

    async def playlist_tracks(self, playlist_id: str):
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        return await self._make_request(url)

    async def artist_albums(self, artist_id: str, album_type: str = 'album', limit: int = 50):
        url = f"https://api.spotify.com/v1/artists/{artist_id}/albums"
        params = {'album_type': album_type, 'limit': limit}
        return await self._make_request(url, params)

    async def album_tracks(self, album_id: str, limit: int = 50):
        url = f"https://api.spotify.com/v1/albums/{album_id}/tracks"
        params = {'limit': limit}
        return await self._make_request(url, params)

    async def next(self, result: dict):
        """Handle pagination"""
        if result and result.get('next'):
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