"""Frozen channel names keep identities, access and owner edits intact."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

from vice_channel_style import (TEAM_CATEGORY_ID, BOT_ID, GUILD_ID, OWNER_ID, VERSION,
                                ChannelStyle, channel_state, format_name,
                                load_manifest, restore_reference, stylize)


class TypographyTests(unittest.TestCase):
    def test_small_caps_normal_digits_accents_and_idempotence(self):
        for name in ('━━ 🛡️ STAFF ━━', '├・📋│pendientes', '╭・🚗│Crew 01', 'guías-y-año',
                     '1️⃣・🔊│🎮 familia 👨‍👩‍👧‍👦', '日本語 🌴'):
            with self.subTest(name=name):
                self.assertEqual(stylize(stylize(name)), stylize(name))
        self.assertEqual(stylize('Staff 12'), 'ꜱᴛᴀꜰꜰ 12')
        self.assertEqual(stylize('STAFF 12'), 'ꜱᴛᴀꜰꜰ 12')
        self.assertEqual(stylize('año'), 'ᴀɴ̃ᴏ')
        self.assertEqual(stylize('guías'), 'ɢᴜɪ́ᴀꜱ')
        self.assertEqual(stylize('𝗦𝗧𝗔𝗙𝗙 𝟭𝟮'), 'ꜱᴛᴀꜰꜰ 12')
        self.assertEqual(stylize('abcdefghijklmnopqrstuvwxyz'), 'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘꞯʀꜱᴛᴜᴠᴡXʏᴢ')

    def test_emoji_graphemes_and_non_latin_names_are_not_rewritten(self):
        for value in ('1️⃣', '2⃣', '#️⃣', '*️⃣', '🇵🇷', '🛡️', '👨‍👩‍👧‍👦', 'Ⓜ️', '①', '日本語', '한글'):
            with self.subTest(value=value):
                self.assertEqual(stylize(value), value)

    def test_live_manifest_restores_exact_original_38_names(self):
        rows, fingerprint = load_manifest()
        reference = restore_reference()
        self.assertEqual(len(rows), 38)
        self.assertEqual({r['id'] for r in rows}, set(reference))
        self.assertEqual(len(fingerprint), 64)
        for row in rows:
            self.assertEqual(row['target_name'], reference[row['id']]['name'])
            self.assertEqual(row['type'], reference[row['id']]['type'])
            self.assertEqual(stylize(row['target_name']), row['target_name'])

    def test_future_creation_keeps_original_layout(self):
        reference = restore_reference()
        for row in reference.values():
            self.assertEqual(format_name(row['name'], category=row['type'] == 4), row['name'])
        for name in ('General', 'Mi canal 01', 'ticket-123', 'reglas-y-guias'):
            self.assertEqual(format_name(name), stylize(name))
            self.assertEqual(format_name(name, category=True), stylize(name))

    def test_manifest_rejects_foreign_identity_duplicates_and_arbitrary_renames(self):
        reference = restore_reference()
        base = dict(version=VERSION, guild_id=str(GUILD_ID), bot_id=str(BOT_ID), owner_id=str(OWNER_ID),
            team_category_id=str(TEAM_CATEGORY_ID), channels=[dict(id=key, type=row['type'],
                name='current-' + key, target_name=row['name']) for key, row in reference.items()])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(json.dumps(base), encoding='utf-8')
            self.assertEqual(len(load_manifest(path)[0]), 38)
            for change in ('foreign', 'duplicate', 'rename', 'unsupported', 'team_missing', 'missing', 'foreign_channel'):
                value = deepcopy(base)
                if change == 'foreign':
                    value['guild_id'] = '999'
                elif change == 'duplicate':
                    value['channels'].append(dict(value['channels'][0]))
                elif change == 'rename':
                    value['channels'][0]['target_name'] = stylize('General')
                elif change == 'unsupported':
                    value['channels'][0]['type'] = 1
                elif change == 'team_missing':
                    value['team_category_id'] = '102'
                elif change == 'missing':
                    value['channels'].pop()
                else:
                    value['channels'][0]['id'] = '999'
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.subTest(change=change), self.assertRaises(ValueError):
                    load_manifest(path)


class ChannelStyleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        team_patch = patch('vice_channel_style.TEAM_CATEGORY_ID', 101)
        team_patch.start()
        self.addCleanup(team_patch.stop)
        self.values = {'category:team': 101}
        self.guild = NS(id=GUILD_ID, owner_id=OWNER_ID)
        self.channels = {}
        self.before = []
        self.rows = [dict(id='101', type=4, name='temporary staff layout',
                         target_name=format_name('━━ 🛡️ ꜱᴛᴀꜰꜰ ━━', category=True)),
                     dict(id='102', type=0, name='temporary log layout',
                          target_name=format_name('├・📋│registro-staff'))]
        for row in self.rows:
            item = NS(id=int(row['id']), type=discord.ChannelType(row['type']), name=row['name'], guild=self.guild,
                      category_id=101 if row['type'] == 0 else None, position=3, topic='Keep this exact topic',
                      _overwrites=[NS(id=GUILD_ID, type=0, allow=0, deny=1024)])
            async def edit(*, name, reason, current=item):
                current.name = name
                return current
            item.edit = AsyncMock(side_effect=edit)
            self.channels[item.id] = item
        async def fetch(channel_id):
            item = self.channels.get(int(channel_id))
            if item is None:
                raise discord.NotFound(NS(status=404, reason='Not Found'), dict(code=10003, message='Unknown Channel'))
            return item
        self.guild.fetch_channel = AsyncMock(side_effect=fetch)
        self.bot = NS(user=NS(id=BOT_ID), get_guild=Mock(return_value=self.guild),
                      fetch_guild=AsyncMock(return_value=self.guild))
        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('Wrong guild')
        async def call(method, key, value=None):
            if method == 'put':
                self.values[key] = deepcopy(value)
            return deepcopy(self.values.get(key))
        async def track(kind, title, operation, request, snapshot):
            self.before.append(await snapshot())
            return await operation()
        self.system = NS(bot=self.bot, validate_guild=validate, store=NS(get=self.values.get),
                         call=AsyncMock(side_effect=call), track=AsyncMock(side_effect=track))
        self.manager = ChannelStyle(self.system)
        self.manifest_patch = patch('vice_channel_style.load_manifest', return_value=(self.rows, 'digest'))
        self.manifest_patch.start()
        self.addCleanup(self.manifest_patch.stop)

    async def test_rename_changes_only_name_and_restart_never_rewrites_owner_changes(self):
        original = {key: channel_state(item) for key, item in self.channels.items()}
        result = await self.manager.ready()
        self.assertEqual(result['changed'], 2)
        for key, item in self.channels.items():
            self.assertEqual(set(item.edit.await_args.kwargs), {'name', 'reason'})
            after = channel_state(item)
            self.assertEqual({k: v for k, v in after.items() if k != 'name'},
                             {k: v for k, v in original[key].items() if k != 'name'})
        self.assertEqual(self.before[0]['before']['name'], self.rows[0]['name'])
        self.channels[102].name = 'Owner changed this later'
        await ChannelStyle(self.system).ready()
        self.assertEqual(self.channels[102].name, 'Owner changed this later')
        for item in self.channels.values():
            item.edit.assert_awaited_once()

    async def test_manual_changes_since_preflight_are_preserved(self):
        self.channels[102].name = 'My custom channel'
        result = await self.manager.ready()
        self.assertEqual(result['manual_change'], 1)
        self.channels[102].edit.assert_not_awaited()
        self.assertEqual(self.values[self.manager.key(102)]['state'], 'manual_change')

    async def test_deleted_objects_are_not_recreated(self):
        del self.channels[102]
        result = await self.manager.ready()
        self.assertEqual(result['absent'], 1)
        self.assertEqual(self.values[self.manager.key(102)]['state'], 'absent')

    async def test_wrong_type_or_foreign_channel_is_never_edited(self):
        self.channels[102].type = discord.ChannelType.voice
        with self.assertLogs('ViceDistrict.channel_style', level='WARNING'), self.assertRaises(ValueError):
            await self.manager.ready()
        self.channels[102].edit.assert_not_awaited()

    async def test_wrong_bot_owner_and_team_mapping_stop_before_any_mutation(self):
        for case in ('bot', 'owner', 'team'):
            self.bot.user.id, self.guild.owner_id = BOT_ID, OWNER_ID
            self.values['category:team'] = 101
            if case == 'bot':
                self.bot.user.id = 99
            elif case == 'owner':
                self.guild.owner_id = 99
            else:
                self.values['category:team'] = 999
            with self.subTest(case=case), self.assertRaises(ValueError):
                await self.manager.ready()
        for item in self.channels.values():
            item.edit.assert_not_awaited()
        self.system.track.assert_not_awaited()

    async def test_mutation_boundary_rechecks_manual_name_and_owner(self):
        original_track = self.system.track.side_effect
        async def changed(kind, title, operation, request, snapshot):
            self.channels[101].name = 'Manual title while queued'
            return await original_track(kind, title, operation, request, snapshot)
        self.system.track.side_effect = changed
        result = await self.manager.ready()
        self.assertEqual(result['manual_change'], 1)
        self.channels[101].edit.assert_not_awaited()

    async def test_lost_rename_response_recovers_from_pending_receipt_without_second_edit(self):
        target = self.channels[102]
        async def lost(*, name, reason):
            target.name = name
            raise OSError('response lost')
        target.edit.side_effect = lost
        with self.assertLogs('ViceDistrict.channel_style', level='WARNING'), self.assertRaises(ValueError):
            await self.manager.ready()
        self.assertEqual(self.values[self.manager.key(102)]['state'], 'pending')
        result = await ChannelStyle(self.system).ready()
        self.assertEqual(result['completed'], 2)
        target.edit.assert_awaited_once()
        self.assertEqual(self.values[self.manager.key(102)]['before']['name'], self.rows[1]['name'])

    async def test_manifest_binding_change_does_not_reuse_receipt(self):
        await self.manager.ready()
        self.values[self.manager.key(102)]['manifest'] = 'different'
        with self.assertLogs('ViceDistrict.channel_style', level='WARNING'), self.assertRaises(ValueError):
            await self.manager.ready()
        self.channels[102].edit.assert_awaited_once()

    async def test_restoration_keeps_previous_pending_receipts_unchanged(self):
        old = {'vice-channel-style-v2:102': {'state': 'pending', 'source_name': 'old v2'},
               'vice-channel-style-v3:102': {'state': 'pending', 'source_name': 'old v3'}}
        self.values.update(deepcopy(old))
        await self.manager.ready()
        self.assertEqual({key: self.values[key] for key in old}, old)
        self.assertEqual(self.values[self.manager.key(102)]['state'], 'completed')


if __name__ == '__main__':
    unittest.main()
