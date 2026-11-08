import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from obscenities import NAME, ObscenityFilter, PATTERNS, WORDS


class FilterTests(unittest.IsolatedAsyncioTestCase):
    def test_standalone_words_and_disguised_forms(self):
        filters = [re.compile(p) for p in PATTERNS] + [
            re.compile(r'\b' + re.escape(w) + r'\b',re.I) for w in WORDS]
        for value in ('¡CB!', 'hdpt', 'HP', 'wlb', 'mmb', 'hijo de puta', 'wuelebicho',
                      'mamabicho', 'c a b r ó n', 'puñ3ta', 'h.d.p.t'):
            self.assertTrue(any(p.search(value) for p in filters),value)
        for value in ('computadora','disputa','la diputada','archivo.php','subir el archivo'):
            self.assertFalse(any(p.search(value) for p in filters),value)

    async def test_enables_only_message_block_once(self):
        user=SimpleNamespace(id=10)
        rule=SimpleNamespace(id=20,enabled=True,creator_id=user.id,name=NAME)
        guild=SimpleNamespace(me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_guild=False)),
                             fetch_automod_rules=AsyncMock(return_value=[]),create_automod_rule=AsyncMock(return_value=rule))
        settings={}
        system=ObscenityFilter(SimpleNamespace(user=user,get_guild=lambda _:guild),1,settings.get,settings.__setitem__)
        await system.install()
        guild.create_automod_rule.assert_not_awaited()
        guild.me.guild_permissions.manage_guild=True
        await system.install()
        params=guild.create_automod_rule.await_args.kwargs
        self.assertEqual([a.to_dict()['type'] for a in params['actions']],[1])
        self.assertTrue(params['enabled'])
        guild.fetch_automod_rules.return_value=[rule]
        await system.install()
        guild.create_automod_rule.assert_awaited_once()
