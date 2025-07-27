import asyncio
import aiohttp
import base64
import time
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from plugins.advanced_spotify_manager import get_spotify_manager
import logging

logger = logging.getLogger(__name__)

class SpotifyMonitor:
    def __init__(self):
        self.status_emojis = {
            'valid': '🟢',
            'invalid': '❌',
            'rate_limited': '🔴',
            'error': '⚠️'
        }

    async def quick_test_client(self, session, client_id, client_secret):
        """Quick test of a single client"""
        try:
            auth_string = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers = {
                'Authorization': f'Basic {auth_string}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {'grant_type': 'client_credentials'}

            async with session.post(
                'https://accounts.spotify.com/api/token',
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return 'valid'
                elif response.status == 429:
                    return 'rate_limited'
                elif response.status in [400, 401]:
                    return 'invalid'
                else:
                    return 'error'
        except Exception as e:
            logger.error(f"Error testing client {client_id[:8]}...: {e}")
            return 'error'

    async def get_detailed_status(self, clients):
        """Get detailed status of all clients"""
        results = []

        async with aiohttp.ClientSession() as session:
            for client in clients:
                client_id = client['client_id']
                client_secret = client['client_secret']

                status = await self.quick_test_client(session, client_id, client_secret)
                results.append({
                    'client_id': client_id,
                    'status': status
                })

                # Small delay between tests
                await asyncio.sleep(0.1)

        return results

@Client.on_message(filters.command("monitor") & filters.private)
async def monitor_clients(client: Client, message: Message):
    """Monitor all Spotify clients in real-time"""

    status_msg = await message.reply("🔍 **Monitoring Spotify clients...**\n⏳ Testing all clients...")

    manager = get_spotify_manager()
    manager.set_telegram_client(client)

    if not manager.clients:
        await status_msg.edit_text("❌ No Spotify clients loaded!")
        return

    monitor = SpotifyMonitor()
    results = await monitor.get_detailed_status(manager.clients)

    # Format results
    response_text = f"🔍 **Spotify Client Monitor**\n"
    response_text += f"📊 **Status of {len(results)} clients:**\n\n"

    valid_count = 0
    rate_limited_count = 0
    invalid_count = 0
    error_count = 0

    for result in results:
        client_id = result['client_id']
        short_id = client_id[:8]
        status = result['status']

        emoji = monitor.status_emojis.get(status, '❓')

        # Get stats from manager
        stats = manager.client_stats.get(client_id, {})
        total_requests = stats.get('requests', 0)

        response_text += f"{emoji} `{short_id}` - {status.title()}"
        if total_requests > 0:
            response_text += f" [Total: {total_requests} reqs]"
        response_text += "\n"

        # Count statuses
        if status == 'valid':
            valid_count += 1
        elif status == 'rate_limited':
            rate_limited_count += 1
        elif status == 'invalid':
            invalid_count += 1
        else:
            error_count += 1

    # Summary
    response_text += f"\n📈 **Summary:**\n"
    response_text += f"✅ Valid: {valid_count}\n"
    response_text += f"🔴 Rate Limited: {rate_limited_count}\n"
    response_text += f"❌ Invalid: {invalid_count}\n"
    response_text += f"⚠️ Errors: {error_count}\n"

    # Current active client
    current_client = manager.get_current_client_id()
    response_text += f"\n🎯 **Current Active:** `{current_client[:8] if current_client != 'None' else 'None'}`"

    if len(response_text) > 4096:
        response_text = response_text[:4090] + "\n\n⚠️ Output truncated..."

    await status_msg.edit_text(response_text)