"""Every copied workflow is confined to the new bot and guild."""
import re
import discord
GUILD_ID = 1514871828189941881
SOURCE_GUILD = 1244988345327550565
SOURCE_BOT = 1567658433497399408

def install():
    original = discord.http.HTTPClient.request
    if getattr(original, '_studio_guard', False):
        return

    async def request(self, route, **kwargs):
        if route.guild_id is not None and int(route.guild_id) != GUILD_ID:
            raise ValueError('EssChino Studio solo puede operar en su propio servidor.')
        if str(SOURCE_GUILD) in route.url or str(SOURCE_BOT) in route.url:
            raise ValueError('Acceso al servidor o bot original bloqueado.')
        return await original(self, route, **kwargs)

    request._studio_guard = True
    discord.http.HTTPClient.request = request
