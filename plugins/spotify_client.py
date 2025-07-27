
# This file has been replaced by the advanced Spotify manager
# Use get_spotify_manager() from plugins.advanced_spotify_manager instead

from plugins.advanced_spotify_manager import get_spotify_manager

# For backward compatibility
async def get_spotify_client():
    """Get Spotify client using the advanced manager"""
    manager = get_spotify_manager()
    return await manager.get_spotify_client()
