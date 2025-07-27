
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
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    token_data = await response.json()
                    return {
                        'status': 'valid',
                        'token': token_data.get('access_token'),
                        'expires_in': token_data.get('expires_in', 3600)
                    }
                elif response.status == 429:
                    return {'status': 'rate_limited'}
                elif response.status in [400, 401]:
                    return {'status': 'invalid'}
                else:
                    return {'status': 'error'}
        except Exception as e:
            logger.error(f"Error testing client {client_id[:8]}...: {e}")
            return {'status': 'error'}

    async def test_all_clients(self, clients, num_requests=10):
        """Test all clients comprehensively"""
        results = []
        
        async with aiohttp.ClientSession() as session:
            for client in clients:
                client_id = client['client_id']
                client_secret = client['client_secret']
                
                # Test credentials
                cred_result = await self.test_client_credentials(session, client_id, client_secret)
                
                result = {
                    'client_id': client_id,
                    'credentials': cred_result['status'],
                    'requests_successful': 0,
                    'requests_failed': 0,
                    'rate_limited': False
                }
                
                # If credentials are valid, test API requests
                if cred_result['status'] == 'valid':
                    token = cred_result['token']
                    headers = {'Authorization': f'Bearer {token}'}
                    
                    for i in range(num_requests):
                        try:
                            async with session.get(
                                'https://api.spotify.com/v1/search',
                                headers=headers,
                                params={'q': 'test', 'type': 'track', 'limit': 1},
                                timeout=aiohttp.ClientTimeout(total=5)
                            ) as response:
                                if response.status == 200:
                                    result['requests_successful'] += 1
                                elif response.status == 429:
                                    result['rate_limited'] = True
                                    result['requests_failed'] += 1
                                else:
                                    result['requests_failed'] += 1
                        except Exception:
                            result['requests_failed'] += 1
                        
                        # Small delay between requests
                        await asyncio.sleep(0.1)
                
                results.append(result)

            async with session.post(
                'https://accounts.spotify.com/api/token',
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    token_data = await response.json()
                    return {
                        'status': 'valid',
                        'token': token_data.get('access_token'),
                        'expires_in': token_data.get('expires_in', 3600)
                    }
                elif response.status == 429:
                    return {'status': 'rate_limited', 'token': None}
                elif response.status in [400, 401]:
                    return {'status': 'invalid', 'token': None}
                else:
                    return {'status': 'error', 'token': None}
        except Exception as e:
            logger.error(f"Error testing credentials for {client_id[:8]}...: {e}")
            return {'status': 'error', 'token': None}

    async def test_api_requests(self, session, token, client_id, num_requests=5):
        """Test API requests with a valid token"""
        successful_requests = 0
        total_time = 0
        errors = []

        headers = {'Authorization': f'Bearer {token}'}
        
        # Test endpoints
        test_urls = [
            'https://api.spotify.com/v1/browse/featured-playlists?limit=1',
            'https://api.spotify.com/v1/browse/categories?limit=1',
            'https://api.spotify.com/v1/browse/new-releases?limit=1'
        ]

        for i in range(num_requests):
            url = test_urls[i % len(test_urls)]
            try:
                start_time = time.time()
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    request_time = time.time() - start_time
                    total_time += request_time

                    if response.status == 200:
                        successful_requests += 1
                    elif response.status == 429:
                        errors.append(f"Rate limited on request {i+1}")
                        break  # Stop testing if rate limited
                    else:
                        errors.append(f"Request {i+1}: HTTP {response.status}")

                # Small delay between requests
                await asyncio.sleep(0.1)

            except Exception as e:
                errors.append(f"Request {i+1}: {str(e)}")

        avg_response_time = total_time / max(successful_requests, 1)

        return {
            'successful_requests': successful_requests,
            'total_requests': num_requests,
            'avg_response_time': avg_response_time,
            'errors': errors
        }

    async def test_all_clients(self, clients, num_requests=10):
        """Test all clients comprehensively"""
        results = []

        async with aiohttp.ClientSession() as session:
            for client in clients:
                client_id = client['client_id']
                client_secret = client['client_secret']

                result = {
                    'client_id': client_id,
                    'credentials_status': 'unknown',
                    'successful_requests': 0,
                    'total_requests': num_requests,
                    'avg_response_time': 0,
                    'errors': []
                }

                # Test credentials first
                cred_result = await self.test_client_credentials(session, client_id, client_secret)
                result['credentials_status'] = cred_result['status']

                # If credentials are valid, test API requests
                if cred_result['status'] == 'valid' and cred_result['token']:
                    api_result = await self.test_api_requests(
                        session, cred_result['token'], client_id, num_requests
                    )
                    result.update(api_result)

                results.append(result)

                # Small delay between clients
                await asyncio.sleep(0.2)

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

    total_valid = 0
    total_invalid = 0
    total_rate_limited = 0

    for result in results:
        client_id = result['client_id']
        short_id = client_id[:8]
        
        if result['credentials'] == 'valid':
            total_valid += 1
            emoji = "🟢"
            status = f"Valid - {result['requests_successful']}/{num_test_requests} requests successful"
            if result['rate_limited']:
                emoji = "🟡"
                status += " (rate limited)"
                total_rate_limited += 1
        elif result['credentials'] == 'invalid':
            total_invalid += 1
            emoji = "❌"
            status = "Invalid credentials"
        elif result['credentials'] == 'rate_limited':
            total_rate_limited += 1
            emoji = "🔴"
            status = "Rate limited during token fetch"
        else:
            emoji = "⚠️"
            status = "Error during testing"

        response_text += f"{emoji} `{short_id}...` - {status}\n"

    response_text += f"\n📈 **Summary:** {total_valid} Valid | {total_invalid} Invalid | {total_rate_limited} Rate Limited"

    if len(response_text) > 4096:
        response_text = response_text[:4000] + "\n\n⚠️ Output truncated..."

    await status_msg.edit_text(response_text)ate_limited = 0

    for result in results:
        client_id = result['client_id']
        short_id = client_id[:8]
        cred_status = result['credentials_status']
        successful_reqs = result.get('successful_requests', 0)
        avg_time = result.get('avg_response_time', 0)

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

        response_text += f"{emoji} `{short_id}` - {cred_status.title()}"
        if successful_reqs > 0:
            response_text += f" ({successful_reqs}/{num_test_requests} reqs, {avg_time:.2f}s avg)"
        response_text += f" [Total: {current_requests}]\n"

    # Summary
    response_text += f"\n📈 **Summary:**\n"
    response_text += f"✅ Valid: {total_valid}\n"
    response_text += f"⚠️ Rate Limited: {total_rate_limited}\n"
    response_text += f"❌ Invalid: {total_invalid}\n"

    if len(response_text) > 4096:
        response_text = response_text[:4090] + "\n\n⚠️ Output truncated..."

    await status_msg.edit_text(response_text)
