"""Direct FiveM health with endpoint discovery from the official join link."""
import asyncio
import ipaddress
import logging
import time
from urllib.parse import urlsplit
import aiohttp

log = logging.getLogger('LaVenganzaRP.fivem')


def dynamic_endpoint(value):
    u = urlsplit(value)
    try:
        address = ipaddress.ip_address(u.hostname or '')
    except ValueError:
        return None
    if u.scheme not in ('http','https') or not address.is_global or u.username or u.password:
        return None
    return f'{u.scheme}://{u.netloc}/dynamic.json'


def healthy(payload):
    return (isinstance(payload,dict) and isinstance(payload.get('clients'),int)
            and not isinstance(payload['clients'],bool) and payload['clients']>=0
            and 'venganza' in str(payload.get('hostname','')).casefold())


class FiveMProbe:
    def __init__(self):
        self.discovered = None
        self.next_discovery = 0
        self.last_result = None

    async def check(self,configured,join):
        endpoints = list(dict.fromkeys(e for e in (configured,self.discovered) if e))
        result = 'unconfigured' if not endpoints else 'unknown'
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=7)) as http:
            for endpoint in endpoints:
                result = await self.read(http,endpoint)
                if result == 'up':
                    return self.record(result,endpoint)
            if time.monotonic() >= self.next_discovery:
                self.next_discovery = time.monotonic()+300
                try:
                    async with http.get(join,allow_redirects=False) as response:
                        endpoint = dynamic_endpoint(response.headers.get('x-citizenfx-url',''))
                    if endpoint:
                        self.discovered = endpoint
                        if endpoint not in endpoints:
                            result = await self.read(http,endpoint)
                except (aiohttp.ClientError,asyncio.TimeoutError):
                    pass
            return self.record(result,configured or self.discovered)

    async def read(self,http,endpoint):
        try:
            async with http.get(endpoint,allow_redirects=False) as response:
                if response.status != 200:
                    return 'unreachable' if response.status in (502,503,504) else 'unknown'
                return 'up' if healthy(await response.json(content_type=None)) else 'unknown'
        except (aiohttp.ClientConnectorError,aiohttp.ServerDisconnectedError,asyncio.TimeoutError):
            return 'unreachable'
        except (aiohttp.ClientError,ValueError):
            return 'unknown'

    def record(self,result,endpoint):
        if (result,endpoint) != self.last_result:
            u = urlsplit(endpoint or '')
            log.info('Lectura directa FiveM: %s host=%s puerto=%s',result,u.hostname,u.port)
            self.last_result = (result,endpoint)
        return result
