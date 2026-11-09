import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from obscenities import NAME, ObscenityFilter, PATTERNS, WORDS, OLD_ABBREVIATION_PATTERN


class FilterTests(unittest.IsolatedAsyncioTestCase):
    def test_standalone_words_and_disguised_forms(self):
        filters = [re.compile(p) for p in PATTERNS] + [
            re.compile(r'\b' + re.escape(w) + r'\b',re.I) for w in WORDS]
        for value in ('¡CB!', 'hdpt', 'HP', 'wlb', 'mmb', 'hijo de puta', 'wuelebicho',
                      'mamabicho', 'c a b r ó n', 'puñ3ta', 'h.d.p.t',
                      'los q están en vc son unos cbnes', 'CBNES', 'c.b.n.e.s', 'c b n e s',
                      'cbn', 'cbns', 'cbrn', 'cbnas', 'cbn3s',
                      'sos una z0rr4', 'chúpame la pija', 'solo sirves para abrir las piernas',
                      'te voy a v1ol4r', 'vamos a violarte', 'MMG', 'triplehijueputa'):
            self.assertTrue(any(p.search(value) for p in filters),value)
        for value in ('computadora','disputa','la diputada','archivo.php','subir el archivo','cabinas','cables','cbnest',
                      'busco a mi perra', 'una zorra cruzó la carretera', 'me picó un bicho',
                      'quiero denunciar acoso sexual','hablamos de consentimiento',
                      'educación sexual y prevención de infecciones','violaron las normas',
                      'la unidad policial investiga una agresión sexual'):
            self.assertFalse(any(p.search(value) for p in filters),value)

    def rule(self,keywords=None,patterns=None,enabled=True,creator=10,actions=None):
        rule=SimpleNamespace(id=20,enabled=enabled,creator_id=creator,name=NAME,
            event_type=discord.AutoModRuleEventType.message_send,
            trigger=discord.AutoModTrigger(keyword_filter=keywords or ['cabron'],regex_patterns=patterns or []),
            actions=actions if actions is not None else [discord.AutoModRuleAction(custom_message='Aviso existente')],
            exempt_role_ids={30},exempt_channel_ids={40})
        def serialized():
            return dict(id=rule.id,enabled=rule.enabled,trigger_metadata=rule.trigger.to_metadata_dict(),
                actions=[a.to_dict() for a in rule.actions],exempt_roles=sorted(rule.exempt_role_ids),exempt_channels=sorted(rule.exempt_channel_ids))
        rule.to_dict=serialized
        return rule

    def setup_system(self,existing=None):
        rules=[existing] if existing else [];settings={'obscenity_rule_id':'20'} if existing else {};snapshots=[]
        guild=SimpleNamespace(id=1,text_channels=[],me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_guild=True)),
            fetch_automod_rules=AsyncMock(side_effect=lambda:list(rules)),fetch_automod_rule=AsyncMock(side_effect=lambda uid:next(r for r in rules if r.id==uid)))
        async def edit(**kwargs):
            self.assertTrue(snapshots,'Save before-state before updating the rule.')
            self.assertEqual(set(kwargs),{'trigger','actions','enabled','reason'})
            existing.trigger=kwargs['trigger'];existing.actions=kwargs['actions'];existing.enabled=kwargs['enabled'];return existing
        if existing:existing.edit=AsyncMock(side_effect=edit)
        async def create(**kwargs):
            self.assertTrue(snapshots)
            rule=self.rule();rule.trigger=kwargs['trigger'];rule.actions=kwargs['actions'];rule.enabled=kwargs['enabled'];rules.append(rule);return rule
        guild.create_automod_rule=AsyncMock(side_effect=create)
        async def tracked(env,title,operation,*,request_id,snapshot):
            snapshots.append(await snapshot());result=await operation();snapshots.append(await snapshot());return result
        client=SimpleNamespace(user=SimpleNamespace(id=10),get_guild=lambda _:guild,changes=SimpleNamespace(tracked=AsyncMock(side_effect=tracked)))
        return ObscenityFilter(client,1,settings.get,settings.__setitem__),guild,settings,snapshots

    def test_native_limits_and_reported_abbreviation_are_covered(self):
        self.assertIn('cbnes',WORDS);self.assertLessEqual(len(WORDS),1000)
        self.assertTrue(all(len(w)<=60 for w in WORDS))
        self.assertLessEqual(len(PATTERNS),10);self.assertTrue(all(len(p)<=260 for p in PATTERNS))

    async def test_creates_a_verified_block_rule_once_with_a_durable_before_state(self):
        system,guild,settings,snapshots=self.setup_system()
        guild.me.guild_permissions.manage_guild=False
        await system.install();guild.create_automod_rule.assert_not_awaited()
        guild.me.guild_permissions.manage_guild=True
        await system.install()
        params=guild.create_automod_rule.await_args.kwargs
        self.assertEqual([a.to_dict()['type'] for a in params['actions']],[1])
        self.assertTrue(params['enabled']);self.assertIsNone(snapshots[0]['rule'])
        self.assertEqual(settings['obscenity_rule_id'],'20')
        self.assertIn('cbnes=True',system.last_status)
        await system.install();guild.create_automod_rule.assert_awaited_once()

    async def test_saved_active_rule_is_updated_in_place_instead_of_being_skipped(self):
        rule=self.rule(patterns=[OLD_ABBREVIATION_PATTERN,*PATTERNS[1:]])
        system,guild,_,snapshots=self.setup_system(rule)
        await system.install()
        rule.edit.assert_awaited_once();guild.create_automod_rule.assert_not_awaited()
        self.assertNotIn('cbnes',snapshots[0]['rule']['trigger_metadata']['keyword_filter'])
        self.assertIn('cbnes',snapshots[1]['rule']['trigger_metadata']['keyword_filter'])
        self.assertEqual(rule.exempt_role_ids,{30});self.assertEqual(rule.exempt_channel_ids,{40})
        self.assertIn(PATTERNS[0],rule.trigger.regex_patterns);self.assertNotIn(OLD_ABBREVIATION_PATTERN,rule.trigger.regex_patterns)
        await system.install();rule.edit.assert_awaited_once()

    async def test_manual_words_patterns_allow_list_exemptions_and_actions_are_preserved(self):
        alert=discord.AutoModRuleAction(channel_id=55)
        rule=self.rule(keywords=['palabra-personalizada'],patterns=[r'patronpersonal',OLD_ABBREVIATION_PATTERN],
            actions=[discord.AutoModRuleAction(custom_message='Aviso existente'),alert])
        rule.trigger.allow_list=['permitido']
        system,_,_,_=self.setup_system(rule);await system.install()
        self.assertIn('palabra-personalizada',rule.trigger.keyword_filter)
        self.assertIn(r'patronpersonal',rule.trigger.regex_patterns);self.assertEqual(rule.trigger.allow_list,['permitido'])
        self.assertEqual(rule.actions[0].custom_message,'Aviso existente');self.assertIs(rule.actions[1],alert)
        self.assertEqual(rule.exempt_role_ids,{30});self.assertEqual(rule.exempt_channel_ids,{40})

    async def test_disabled_or_alert_only_own_rule_gets_blocking_without_new_punishments(self):
        rule=self.rule(enabled=False,actions=[discord.AutoModRuleAction(channel_id=55)])
        system,_,_,_=self.setup_system(rule);await system.install()
        self.assertTrue(rule.enabled)
        self.assertEqual({a.type for a in rule.actions},{discord.AutoModRuleActionType.send_alert_message,discord.AutoModRuleActionType.block_message})

    async def test_another_applications_rule_is_never_modified(self):
        rule=self.rule(creator=99);system,guild,_,snapshots=self.setup_system(rule)
        await system.install()
        rule.edit.assert_not_awaited();guild.create_automod_rule.assert_not_awaited();self.assertFalse(snapshots)

    async def test_unconfirmed_readback_does_not_report_a_working_filter(self):
        rule=self.rule();system,guild,_,_=self.setup_system(rule)
        guild.fetch_automod_rule.return_value=self.rule()
        guild.fetch_automod_rule.side_effect=None
        await system.install()
        self.assertIn('no confirmó',system.last_status)
        self.assertNotIn('regla verificada',system.last_status)
