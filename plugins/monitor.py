
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
            'active': '🟢',
            'working': '🟢', 
            'valid': '🟢',
            'rate_limited': '🔴',
            'invalid': '❌',
            'testing': '🔄',
            'error': '⚠️',
            'unknown': '❓'
        }
    
    async def quick_test_client(self, session, client_id, client_secret):
        """Quick test to check if client is working"""
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
                    return 'working'
                elif response.status == 429:
                    return 'rate_limited'
                elif response.status in [400, 401]:
                    return 'invalid'
                else:
                    return 'error'
        except asyncio.TimeoutError:
            return 'timeout'
        except Exception:
            return 'error'
    
    async def get_detailed_status(self, clients):
        """Get detailed status for all clients"""
        results = {}
        
        async with aiohttp.ClientSession() as session:
            # Test all clients concurrently for faster results
            tasks = []
            for client in clients:
                client_id = client['client_id']
                client_secret = client['client_secret']
                task = self.quick_test_client(session, client_id, client_secret)
                tasks.append((client_id, task))
            
            # Wait for all tests to complete
            for client_id, task in tasks:
                try:
                    status = await task
                    results[client_id] = status
                except Exception:
                    results[client_id] = 'error'
        
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
    
    # Monitoring loop (run once or continuously)
    iteration = 0
    while True:
        iteration += 1
        start_time = time.time()
        
        # Get current manager stats
        manager_stats = manager.client_stats
        current_client_id = manager.get_current_client_id()
        
        # Test all clients
        test_results = await monitor.get_detailed_status(manager.clients)
        
        # Build comprehensive status report
        response_text = f"📊 **Spotify Clients Monitor**"
        if auto_refresh:
            response_text += f" (Update #{iteration})"
        response_text += f"\n🕐 **Last Updated:** {datetime.now().strftime('%H:%M:%S')}\n\n"
        
        # Summary counters
        status_counts = {
            'working': 0,
            'rate_limited': 0,
            'invalid': 0,
            'error': 0
        }
        
        # Client details
        for i, client_data in enumerate(manager.clients):
            client_id = client_data['client_id']
            short_id = client_id[:8]
            
            # Get test result
            test_status = test_results.get(client_id, 'unknown')
            
            # Get manager stats
            stats = manager_stats.get(client_id, {})
            session_requests = stats.get('requests', 0)
            manager_status = stats.get('status', 'unknown')
            
            # Determine final status and emoji
            if test_status == 'working':
                emoji = monitor.status_emojis['working']
                status_text = "Working"
                status_counts['working'] += 1
            elif test_status == 'rate_limited':
                emoji = monitor.status_emojis['rate_limited']
                status_text = "Rate Limited"
                status_counts['rate_limited'] += 1
            elif test_status == 'invalid':
                emoji = monitor.status_emojis['invalid']
                status_text = "Invalid Credentials"
                status_counts['invalid'] += 1
            else:
                emoji = monitor.status_emojis['error']
                status_text = f"Error ({test_status})"
                status_counts['error'] += 1
            
            # Mark current active client
            is_current = client_id == current_client_id
            current_marker = " 🎯" if is_current else ""
            
            # Build client line
            response_text += f"{emoji} `{short_id}` – {status_text}"
            
            if session_requests > 0:
                response_text += f" | {session_requests} reqs"
            
            response_text += current_marker
            response_text += "\n"
        
        # Summary statistics
        total_clients = len(manager.clients)
        response_text += f"\n📈 **Summary:**\n"
        response_text += f"🟢 Working: {status_counts['working']}/{total_clients}\n"
        response_text += f"🔴 Rate Limited: {status_counts['rate_limited']}/{total_clients}\n"
        response_text += f"❌ Invalid: {status_counts['invalid']}/{total_clients}\n"
        response_text += f"⚠️ Errors: {status_counts['error']}/{total_clients}\n"
        
        # Current active client details
        if current_client_id:
            current_stats = manager_stats.get(current_client_id, {})
            current_requests = current_stats.get('requests', 0)
            last_used = current_stats.get('last_used')
            
            response_text += f"\n🎯 **Active Client:**\n"
            response_text += f"`{current_client_id[:8]}` | {current_requests} requests"
            
            if last_used:
                response_text += f" | Last: {last_used.strftime('%H:%M:%S')}"
        
        # Performance info
        test_time = round((time.time() - start_time) * 1000, 1)
        response_text += f"\n\n⚡ Test completed in {test_time}ms"
        
        # Auto-refresh info
        if auto_refresh:
            response_text += f"\n🔄 Auto-refreshing every 30s... (Use /monitor to stop)"
        
        # Update message
        try:
            await status_msg.edit_text(response_text)
        except Exception as e:
            # If message is too long, create new one
            if "too long" in str(e).lower():
                await status_msg.edit_text(response_text[:4000] + "\n\n⚠️ *Output truncated*")
            else:
                logger.error(f"Failed to update monitor message: {e}")
        
        # Break if not auto-refresh mode
        if not auto_refresh:
            break
        
        # Wait before next refresh
        await asyncio.sleep(30)
        
        # Safety: stop after 20 iterations to prevent spam
        if iteration >= 20:
            await status_msg.edit_text(response_text + "\n\n⏹️ *Auto-refresh stopped (limit reached)*")
            break

@Client.on_message(filters.command("status") & filters.private)
async def quick_status(client: Client, message: Message):
    """Quick status overview without detailed testing"""
    
    manager = get_spotify_manager()
    manager.set_telegram_client(client)
    
    if not manager.clients:
        await message.reply("❌ No Spotify clients loaded!")
        return
    
    monitor = SpotifyMonitor()
    
    # Get manager stats without testing
    response_text = f"⚡ **Quick Status Overview**\n🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
    
    current_client_id = manager.get_current_client_id()
    
    # Summary from manager stats only
    active_count = 0
    rate_limited_count = 0
    
    for client_data in manager.clients:
        client_id = client_data['client_id']
        short_id = client_id[:8]
        stats = manager.client_stats.get(client_id, {})
        
        status = stats.get('status', 'unknown')
        requests = stats.get('requests', 0)
        
        if status == 'active':
            emoji = monitor.status_emojis['active']
            active_count += 1
        elif status == 'rate_limited':
            emoji = monitor.status_emojis['rate_limited']
            rate_limited_count += 1
        else:
            emoji = monitor.status_emojis['unknown']
        
        is_current = client_id == current_client_id
        current_marker = " 🎯" if is_current else ""
        
        response_text += f"{emoji} `{short_id}` – {requests} reqs{current_marker}\n"
    
    # Summary
    total = len(manager.clients)
    response_text += f"\n📊 Active: {active_count} | Rate Limited: {rate_limited_count} | Total: {total}"
    response_text += f"\n\n💡 Use `/monitor` for detailed testing"
    
    await message.reply(response_text)
