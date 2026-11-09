import unittest
from unittest.mock import AsyncMock,MagicMock,patch
from fivem_probe import FiveMProbe,dynamic_endpoint,healthy


class FiveMTests(unittest.IsolatedAsyncioTestCase):
    def test_only_public_discovered_addresses_are_used(self):
        for url in ('http://127.0.0.1:30120/','http://10.0.0.2/','file:///x','http://user:secret@23.26.96.205/'):
            self.assertIsNone(dynamic_endpoint(url))
        self.assertEqual(dynamic_endpoint('http://23.26.96.205:30120/'),'http://23.26.96.205:30120/dynamic.json')

    def test_requires_actual_server_payload_not_a_join_page(self):
        self.assertTrue(healthy(dict(hostname='La Venganza RP',clients=0)))
        self.assertFalse(healthy(dict(hostname='Other server',clients=30)))
        self.assertFalse(healthy(dict(hostname='La Venganza',clients=True)))
        self.assertFalse(healthy('<html>Join</html>'))

    async def test_discovers_official_endpoint_and_checks_it_live(self):
        probe=FiveMProbe()
        with patch('fivem_probe.aiohttp.ClientSession') as factory:
            session=factory.return_value.__aenter__.return_value
            session.get=MagicMock()
            session.get.return_value.__aenter__.return_value.headers={'x-citizenfx-url':'http://23.26.96.205:30120/'}
            with patch.object(probe,'read',AsyncMock(side_effect=['unreachable','up'])) as read:
                result=await probe.check('http://old.example/dynamic.json','https://cfx.re/join/57vjg7')
                self.assertEqual(result,'up')
                self.assertEqual(read.await_args.args[1],'http://23.26.96.205:30120/dynamic.json')
