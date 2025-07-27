import aiohttp
import asyncio
import itertools
import base64
import logging

logger = logging.getLogger(__name__)

class SpotifyClientManager:
    def __init__(self, clients):
        self.clients = clients
        self.client_cycle = itertools.cycle(clients)
        self.current_token = None
        self.token_expiry = 0
        self.lock = asyncio.Lock() 

        # Rate limiting tracking
        self.request_counter = 0
        self.window_start = asyncio.get_event_loop().time()

    async def _get_token(self, client_id, client_secret):
        url = "https://accounts.spotify.com/api/token"
        creds = f"{client_id}:{client_secret}"
        b64_creds = base64.b64encode(creds.encode()).decode()
        headers = {
            "Authorization": f"Basic {b64_creds}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"grant_type": "client_credentials"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Failed to get token: {resp.status} {text}")
                    return None, 0
                res = await resp.json()
                return res.get("access_token"), res.get("expires_in", 3600)

    async def make_request(self, url, params=None):
        async with self.lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.window_start

            # Reset counter every 60 seconds
            if elapsed > 60:
                self.request_counter = 0
                self.window_start = now

            # If limit reached, wait until window resets
            if self.request_counter >= 80:
                wait_time = 60 - elapsed
                logger.info(f"Rate limit reached. Waiting for {wait_time:.2f} seconds...")
                await asyncio.sleep(wait_time)
                self.request_counter = 0
                self.window_start = asyncio.get_event_loop().time()

            # Rotate client for each request
            client = next(self.client_cycle)

            # Get new token if expired or none
            if self.current_token is None or now >= self.token_expiry or client != getattr(self, 'current_client', None):
                token, expires_in = await self._get_token(client["client_id"], client["client_secret"])
                if token is None:
                    logger.error(f"Skipping client {client['client_id']} due to token fetch failure.")
                    self.current_token = None
                    self.token_expiry = 0
                    return None
                self.current_token = token
                self.token_expiry = now + expires_in - 60
                self.current_client = client
             

            headers = {"Authorization": f"Bearer {self.current_token}"}

            # Increment request count after headers prepared
            self.request_counter += 1

        # Make request outside lock
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning(f"Rate limited by Spotify. Sleeping for {retry_after} seconds...")
                    await asyncio.sleep(retry_after + 1)
                    return None
                elif resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Spotify API error {resp.status}: {text}")
                    return None
                return await resp.json()
