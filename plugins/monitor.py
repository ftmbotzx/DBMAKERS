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
            tasks = []
            for client in clients:
                task = self.quick_test_client(session, client['client_id'], client['client_secret'])
                tasks.append(task)

            statuses = await asyncio.gather(*tasks, return_exceptions=True)

            for i, client in enumerate(clients):
                status = statuses[i] if not isinstance(statuses[i], Exception) else 'error'
                results.append({
                    'client_id': client['client_id'],
                    'status': status
                })

        return results

@Client.on_message(filters.command("monitor") & filters.private)
async def monitor_spotify_clients(client: Client, message: Message):
    """Real-time monitoring of all Spotify clients with comprehensive status"""

    # Parse arguments for refresh option
    args = message.command[1:] if len(message.command) > 1 else []
    auto_refresh = False
    if args and args[0].lower() in ['auto', 'refresh', 'live']:
        auto_refresh = True

    # Initial status message
    status_msg = await message.reply("🔄 **Monitoring Spotify Clients...**\n⏳ Testing all clients...")

    # Get manager and clients
    manager = get_spotify_manager()
    manager.set_telegram_client(client)

    if not manager.clients:
        await status_msg.edit_text("❌ No Spotify clients loaded!")
        return

    monitor = SpotifyMonitor()

    while True:
        start_time = time.time()

        # Get current client info
        current_client_id = manager.get_current_client_id()
        manager_stats = manager.client_stats

        # Test all clients
        test_results = await monitor.get_detailed_status(manager.clients)

        # Count statuses
        valid_count = sum(1 for r in test_results if r['status'] == 'valid')
        invalid_count = sum(1 for r in test_results if r['status'] == 'invalid')
        rate_limited_count = sum(1 for r in test_results if r['status'] == 'rate_limited')
        active_count = valid_count

        # Build response
        response_text = f"📊 **Spotify Clients Monitor**\n"
        response_text += f"🕐 **Last Update:** {datetime.now().strftime('%H:%M:%S')}\n\n"

        # Current client info
        if current_client_id:
            current_short = current_client_id[:8]
            response_text += f"⭐ **Current Client:** `{current_short}...`\n\n"

        # Summary
        response_text += f"📈 **Summary:** {valid_count} Valid | {rate_limited_count} Rate Limited | {invalid_count} Invalid\n\n"

        # Individual client status
        response_text += "📋 **Individual Status:**\n"
        for result in test_results:
            client_id = result['client_id']
            short_id = client_id[:8]
            status = result['status']
            emoji = monitor.status_emojis.get(status, '❓')

            # Add manager stats if available
            manager_stat = manager_stats.get(client_id, {})
            requests_count = manager_stat.get('requests', 0)

            status_line = f"{emoji} `{short_id}...` - {status}"
            if requests_count > 0:
                status_line += f" ({requests_count} reqs)"
            if client_id == current_client_id:
                status_line += " ⭐"

            response_text += f"{status_line}\n"

        # Performance info
        test_duration = time.time() - start_time
        response_text += f"\n⏱️ **Test Duration:** {test_duration:.2f}s"

        # Update message
        if len(response_text) > 4096:
            response_text = response_text[:4000] + "\n\n⚠️ Output truncated..."

        await status_msg.edit_text(response_text)

        # Break if not auto-refresh
        if not auto_refresh:
            break

        # Wait before next update (only if auto-refresh)
        await asyncio.sleep(30)  # Update every 30 seconds

@Client.on_message(filters.command("status") & filters.private)
async def quick_status_check(client: Client, message: Message):
    """Quick status check of all clients"""

    status_msg = await message.reply("🔍 **Quick Status Check...**")

    # Get manager
    manager = get_spotify_manager()
    manager.set_telegram_client(client)

    if not manager.clients:
        await status_msg.edit_text("❌ No Spotify clients loaded!")
        return

    # Quick count from manager stats
    manager_stats = manager.client_stats
    current_client_id = manager.get_current_client_id()

    active_count = 0
    rate_limited_count = 0

    response_text = f"⚡ **Quick Status Check**\n\n"

    for client_data in manager.clients:
        client_id = client_data['client_id']
        short_id = client_id[:8]

        stats = manager_stats.get(client_id, {})
        requests = stats.get('requests', 0)
        status = stats.get('status', 'unknown')

        if status == 'active':
            active_count += 1
            emoji = "🟢"
        elif status == 'rate_limited':
            rate_limited_count += 1
            emoji = "🔴"
        else:
            emoji = "❓"

        current_marker = " ⭐" if client_id == current_client_id else ""
        response_text += f"{emoji} `{short_id}` – {requests} reqs{current_marker}\n"

    # Summary
    total = len(manager.clients)
    response_text += f"\n📊 Active: {active_count} | Rate Limited: {rate_limited_count} | Total: {total}"
    response_text += f"\n⭐ Current: `{current_client_id[:8] if current_client_id else 'None'}...`"

    await status_msg.edit_text(response_text)