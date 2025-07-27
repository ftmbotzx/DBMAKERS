
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

class SpotifyClientTester:
    def __init__(self):
        self.test_results = {}
        
    async def test_client_credentials(self, session, client_id, client_secret):
        """Test a single client's credentials and get token"""
        auth_string = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {
            'Authorization': f'Basic {auth_string}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {'grant_type': 'client_credentials'}
        
        try:
            async with session.post(
                'https://accounts.spotify.com/api/token',
                headers=headers,
                data=data
            ) as response:
                if response.status == 200:
                    token_data = await response.json()
                    return {
                        'status': 'valid',
                        'token': token_data.get('access_token'),
                        'expires_in': token_data.get('expires_in', 3600)
                    }
                elif response.status == 429:
                    retry_after = response.headers.get('Retry-After', 'unknown')
                    return {
                        'status': 'rate_limited',
                        'retry_after': retry_after,
                        'token': None
                    }
                elif response.status in [400, 401]:
                    return {
                        'status': 'invalid',
                        'token': None
                    }
                else:
                    return {
                        'status': f'error_{response.status}',
                        'token': None
                    }
        except Exception as e:
            return {
                'status': f'error: {str(e)}',
                'token': None
            }
    
    async def test_api_requests(self, session, token, client_id, num_requests=10):
        """Test API requests with a valid token"""
        headers = {'Authorization': f'Bearer {token}'}
        request_results = []
        
        # Test endpoint: search for a simple query
        test_url = 'https://api.spotify.com/v1/search'
        test_params = {'q': 'test', 'type': 'track', 'limit': 1}
        
        for i in range(num_requests):
            try:
                start_time = time.time()
                async with session.get(test_url, headers=headers, params=test_params) as response:
                    end_time = time.time()
                    response_time = round((end_time - start_time) * 1000, 2)  # ms
                    
                    if response.status == 200:
                        request_results.append({
                            'request': i + 1,
                            'status': 'success',
                            'response_time': response_time
                        })
                    elif response.status == 429:
                        retry_after = response.headers.get('Retry-After', 'unknown')
                        request_results.append({
                            'request': i + 1,
                            'status': 'rate_limited',
                            'retry_after': retry_after
                        })
                        break  # Stop testing if rate limited
                    else:
                        request_results.append({
                            'request': i + 1,
                            'status': f'error_{response.status}',
                            'response_time': response_time
                        })
                        
                # Small delay between requests
                await asyncio.sleep(0.1)
                
            except Exception as e:
                request_results.append({
                    'request': i + 1,
                    'status': f'exception: {str(e)}'
                })
        
        return request_results
    
    async def test_all_clients(self, clients, num_test_requests=10):
        """Test all clients comprehensively"""
        results = {}
        
        async with aiohttp.ClientSession() as session:
            for client in clients:
                client_id = client['client_id']
                client_secret = client['client_secret']
                
                logger.info(f"Testing client: {client_id[:8]}...")
                
                # Test credentials
                cred_result = await self.test_client_credentials(session, client_id, client_secret)
                
                results[client_id] = {
                    'client_id_short': client_id[:8],
                    'credential_test': cred_result,
                    'api_requests': [],
                    'total_successful_requests': 0,
                    'avg_response_time': 0
                }
                
                # If credentials are valid, test API requests
                if cred_result['status'] == 'valid' and cred_result['token']:
                    api_results = await self.test_api_requests(
                        session, 
                        cred_result['token'], 
                        client_id, 
                        num_test_requests
                    )
                    results[client_id]['api_requests'] = api_results
                    
                    # Calculate stats
                    successful_requests = [r for r in api_results if r['status'] == 'success']
                    results[client_id]['total_successful_requests'] = len(successful_requests)
                    
                    if successful_requests:
                        avg_time = sum(r['response_time'] for r in successful_requests) / len(successful_requests)
                        results[client_id]['avg_response_time'] = round(avg_time, 2)
                
                # Small delay between clients
                await asyncio.sleep(0.5)
        
        return results

@Client.on_message(filters.command("client") & filters.private)
async def test_spotify_clients(client: Client, message: Message):
    """Test all Spotify clients comprehensively"""
    
    # Parse command arguments
    args = message.command[1:] if len(message.command) > 1 else []
    num_test_requests = 10  # default
    
    if args:
        try:
            num_test_requests = int(args[0])
            if num_test_requests > 50:
                num_test_requests = 50  # limit to prevent abuse
        except ValueError:
            await message.reply("❗ Invalid number. Usage: `/client [number_of_test_requests]`")
            return
    
    status_msg = await message.reply(f"🧪 **Testing all Spotify clients...**\n⏳ Testing credentials and performing {num_test_requests} API requests per client...")
    
    # Get clients from manager
    manager = get_spotify_manager()
    manager.set_telegram_client(client)
    
    if not manager.clients:
        await status_msg.edit_text("❌ No Spotify clients loaded!")
        return
    
    # Run comprehensive tests
    tester = SpotifyClientTester()
    results = await tester.test_all_clients(manager.clients, num_test_requests)
    
    # Format results
    response_text = f"🧪 **Spotify Clients Test Results**\n"
    response_text += f"📊 **Tested {len(results)} clients with {num_test_requests} requests each**\n\n"
    
    # Get current stats from manager
    current_stats = manager.get_client_status()
    
    total_valid = 0
    total_invalid = 0
    total_rate_limited = 0
    
    for client_id, result in results.items():
        short_id = result['client_id_short']
        cred_status = result['credential_test']['status']
        successful_reqs = result['total_successful_requests']
        avg_time = result['avg_response_time']
        
        # Status emoji
        if cred_status == 'valid':
            if successful_reqs == num_test_requests:
                emoji = "🟢"
                total_valid += 1
            elif successful_reqs > 0:
                emoji = "🟡"
                total_valid += 1
            else:
                emoji = "🔴"
                total_rate_limited += 1
        elif cred_status == 'rate_limited':
            emoji = "⚠️"
            total_rate_limited += 1
        elif cred_status == 'invalid':
            emoji = "❌"
            total_invalid += 1
        else:
            emoji = "❓"
        
        # Get current requests from manager stats
        current_requests = manager.client_stats.get(client_id, {}).get('requests', 0)
        
        response_text += f"{emoji} `{short_id}` – "
        
        if cred_status == 'valid':
            response_text += f"{successful_reqs}/{num_test_requests} reqs"
            if avg_time > 0:
                response_text += f" ({avg_time}ms avg)"
            if current_requests > 0:
                response_text += f" | Session: {current_requests}"
        elif cred_status == 'rate_limited':
            retry_after = result['credential_test'].get('retry_after', 'unknown')
            response_text += f"Rate Limited (retry: {retry_after}s)"
        elif cred_status == 'invalid':
            response_text += "Invalid Credentials"
        else:
            response_text += f"Error: {cred_status}"
        
        response_text += "\n"
    
    # Summary
    response_text += f"\n📈 **Summary:**\n"
    response_text += f"🟢 Valid & Working: {total_valid}\n"
    response_text += f"🔴 Rate Limited: {total_rate_limited}\n"
    response_text += f"❌ Invalid: {total_invalid}\n"
    
    # Current active client
    current_client_id = manager.get_current_client_id()
    if current_client_id and current_client_id != "None":
        response_text += f"\n🎯 **Current Active:** `{current_client_id[:8]}`"
    
    response_text += f"\n\n💡 Use `/monitor` for real-time monitoring"
    
    # Split message if too long
    if len(response_text) > 4096:
        # Send first part
        await status_msg.edit_text(response_text[:4000] + "\n\n⚠️ *Output truncated - too long*")
        
        # Send remaining as new message
        remaining = response_text[4000:]
        if remaining:
            await message.reply(remaining[:4096])
    else:
        await status_msg.edit_text(response_text)
