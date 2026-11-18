"""Guild privacy, catch-up, output batching and send-crash recovery."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from vice_audit import ViceAudit, embed_marker, fit_batch, marker, semantic_embeds
from vice_design import GUILD_ID, BOT_ID, OWNER_ID


class AuditRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.guild.default_role = MagicMock(spec=discord.Role)
        self.guild.default_role.id = GUILD_ID
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id = BOT_ID
        self.guild.me.guild_permissions = discord.Permissions(view_audit_log=True)
        self.bot = NS(user=NS(id=BOT_ID), get_guild=MagicMock(return_value=self.guild))
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild, self.channel.topic = 7001, self.guild, 'Old topic'
        self.channel.overwrites = {self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                                   self.guild.me: discord.PermissionOverwrite(view_channel=True)}
        self.channel.overwrites_for.side_effect = lambda target: self.channel.overwrites.get(target, discord.PermissionOverwrite())
        self.channel.permissions_for.return_value = discord.Permissions(
            view_channel=True, send_messages=True, embed_links=True, read_message_history=True)
        self.values = {'channel:log': self.channel.id, 'role:founder': 11, 'role:admin': 12,
                       'role:mod': 13, 'role:support': 14}
        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')
        self.snapshots, self.messages = [], []
        async def track(kind, title, operation, request, snapshot=None):
            self.snapshots.append(await snapshot())
            return await operation()
        self.system = NS(path=Path(self.tmp.name) / 'vice.sqlite3', bot=self.bot,
                         validate_guild=validate, channel=lambda guild, key: self.channel,
                         channel_id=lambda key: self.values.get('channel:' + key),
                         store=NS(get=self.values.get), track=AsyncMock(side_effect=track),
                         panel=AsyncMock())
        self.audit = ViceAudit(self.system)
        await self.audit.start()
        self.addAsyncCleanup(self.audit.close)
        async def send(**kwargs):
            msg = self.message(9000 + len(self.messages), kwargs['embeds'])
            self.messages.append(msg)
            return msg
        async def fetch(message_id):
            return next(m for m in self.messages if m.id == message_id)
        async def history(**kwargs):
            for message in self.messages:
                yield message
        self.channel.send = AsyncMock(side_effect=send)
        self.channel.fetch_message = AsyncMock(side_effect=fetch)
        self.channel.history = MagicMock(side_effect=history)
        self.when = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)

    def message(self, message_id, embeds, author=BOT_ID):
        msg = NS(id=message_id, author=NS(id=author),
                 embeds=[discord.Embed.from_dict(e.to_dict()) for e in embeds])
        async def edit(**kwargs):
            msg.embeds = [discord.Embed.from_dict(e.to_dict()) for e in kwargs['embeds']]
            return msg
        msg.edit = AsyncMock(side_effect=edit)
        return msg

    def embed(self, name='Canal actualizado', size=80):
        e = discord.Embed(title=name, description='D' * size, timestamp=self.when)
        e.set_author(name='esschino')
        e.set_footer(text='VIce District • 18/11/2026 08:00:00 AST · Puerto Rico')
        e.add_field(name='Responsable', value=f'<@{OWNER_ID}>')
        e.add_field(name='IDs', value=f'Responsable: `{OWNER_ID}`\nAuditoría: `1572621740033446082`')
        return e

    async def queue(self, key, *, historical=True, size=80, when=None):
        await self.audit.publish(key, self.embed(size=size), event_type='audit',
                                 event_time=when or self.when, historical=historical)

    async def test_destination_rejects_foreign_guild_owner_bot_or_member(self):
        for attr, value in [('id', 123), ('owner_id', 123)]:
            original = getattr(self.guild, attr)
            setattr(self.guild, attr, value)
            with self.subTest(attr=attr), self.assertRaises(ValueError):
                self.audit.destination()
            setattr(self.guild, attr, original)
        self.bot.user.id = 123
        with self.assertRaises(ValueError):
            self.audit.destination()
        self.bot.user.id = BOT_ID
        self.guild.me = NS(id=123)
        with self.assertRaisesRegex(ValueError, 'miembro'):
            self.audit.destination()
        self.channel.send.assert_not_awaited()

    async def test_destination_fails_closed_on_public_or_nonstaff_access_and_missing_permissions(self):
        self.assertIs(self.audit.destination(), self.channel)
        self.channel.overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=True)
        with self.assertRaisesRegex(ValueError, 'privado'):
            self.audit.destination()
        self.channel.overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=False)
        intruder = MagicMock(spec=discord.Role)
        intruder.id = 9999
        self.channel.overwrites[intruder] = discord.PermissionOverwrite(view_channel=True)
        with self.assertRaisesRegex(ValueError, 'ajeno'):
            self.audit.destination()
        del self.channel.overwrites[intruder]
        self.channel.permissions_for.return_value = discord.Permissions(view_channel=True, send_messages=True)
        with self.assertRaisesRegex(ValueError, 'leer y publicar'):
            self.audit.destination()
        self.channel.send.assert_not_awaited()

    async def test_historical_batch_maximum_five_then_live_individual(self):
        for i in range(6):
            await self.queue(f'audit:{i}')
        await self.queue('voice:1', historical=False, when=self.when + timedelta(hours=1))
        await self.queue('voice:2', historical=False, when=self.when + timedelta(hours=2))
        while await self.audit.flush_once():
            pass
        self.assertEqual([len(m.embeds) for m in self.messages], [5, 1, 1, 1])
        self.assertEqual(self.audit.store.stats()['sent'], 8)
        for call in self.channel.send.await_args_list:
            self.assertLessEqual(len(call.kwargs['nonce']), 25)
            self.assertTrue(call.kwargs['silent'])
            self.assertFalse(call.kwargs['allowed_mentions'].everyone)
        self.assertEqual(self.snapshots[0]['channel'], self.channel.id)

    async def test_historical_batch_respects_combined_embed_budget(self):
        for i in range(3):
            await self.queue(f'audit:{i}', size=2200)
        await self.audit.flush_once()
        self.assertEqual(len(self.messages[0].embeds), 2)
        self.assertLessEqual(sum(len(e) for e in self.messages[0].embeds), 5500)
        self.assertEqual(self.audit.store.stats()['pending'], 1)

    async def test_send_then_database_failure_recovers_exact_message_without_second_send(self):
        await self.queue('audit:recover')
        original = self.audit.db
        failed = False
        async def interrupted(method, *args, **kwargs):
            nonlocal failed
            if method == 'mark_sent' and not failed:
                failed = True
                raise OSError('crash after Discord accepted send')
            return await original(method, *args, **kwargs)
        with patch.object(self.audit, 'db', side_effect=interrupted):
            with self.assertRaises(OSError):
                await self.audit.flush_once()
        self.assertEqual(len(self.messages), 1)
        self.assertIsNone(self.audit.store.get('audit:recover')['message_id'])
        restarted = ViceAudit(self.system)
        await restarted.start()
        await restarted.flush_once()
        self.channel.send.assert_awaited_once()
        self.messages[0].edit.assert_awaited_once()
        self.assertEqual(restarted.store.get('audit:recover')['message_id'], str(self.messages[0].id))
        self.assertFalse(await restarted.flush_once())
        self.channel.history.assert_called_once()
        self.assertIsNone(self.channel.history.call_args.kwargs['limit'])

    async def test_nonce_response_with_older_body_is_updated_before_acknowledgement(self):
        new = self.embed()
        new.add_field(name='Cantidad acumulada', value='4')
        await self.audit.publish('audit:nonce', new, event_type='audit', event_time=self.when)
        desired = self.audit.embeds([self.audit.store.get('audit:nonce')])[0]
        old = discord.Embed.from_dict(deepcopy(desired.to_dict()))
        old.set_field_at(len(old.fields) - 1, name='Cantidad acumulada', value='1')
        previous = self.message(9101, [old])
        self.messages.append(previous)
        self.channel.send.side_effect = None
        self.channel.send.return_value = previous
        await self.audit.flush_once()
        previous.edit.assert_awaited_once()
        self.assertEqual(semantic_embeds(previous.embeds), semantic_embeds([desired]))
        self.assertEqual(self.audit.store.get('audit:nonce')['message_id'], '9101')
        self.assertEqual(self.audit.store.stats()['pending'], 0)

    async def test_returned_cdn_metadata_does_not_cause_spurious_edit(self):
        e = self.embed()
        e.set_thumbnail(url='https://cdn.discordapp.com/avatars/1/icon.png')
        await self.audit.publish('audit:cdn', e, event_type='audit', event_time=self.when)
        returned = self.audit.embeds([self.audit.store.get('audit:cdn')])[0].to_dict()
        returned['type'] = 'rich'
        returned['thumbnail'].update(proxy_url='https://media.discordapp.net/icon.png', width=128, height=128)
        returned['author']['proxy_icon_url'] = 'https://media.discordapp.net/author.png'
        msg = self.message(9102, [discord.Embed.from_dict(returned)])
        self.channel.send.side_effect = None
        self.channel.send.return_value = msg
        await self.audit.flush_once()
        msg.edit.assert_not_awaited()
        self.assertEqual(self.audit.store.stats()['pending'], 0)

    async def test_discord_drops_embed_url_and_footer_fallback_is_verified_before_ack(self):
        card = discord.Embed(description=f'<@{OWNER_ID}> actualizó un canal.', timestamp=self.when)
        card.set_author(name='esschino')
        card.set_footer(text='VIce District • 18/11/2026 08:00 AST')
        await self.audit.publish('audit:stripped-url', card, event_type='audit', event_time=self.when)
        def strip_urls(embeds):
            values = []
            for embed in embeds:
                value = deepcopy(embed.to_dict())
                value.pop('url', None)
                values.append(discord.Embed.from_dict(value))
            return values
        async def send(**kwargs):
            message = self.message(9103, strip_urls(kwargs['embeds']))
            async def edit(**changes):
                message.embeds = strip_urls(changes['embeds'])
                return message
            message.edit = AsyncMock(side_effect=edit)
            self.messages.append(message)
            return message
        self.channel.send.side_effect = send
        real_db = self.audit.db
        acknowledged = []
        async def db(method, *args, **kwargs):
            if method == 'mark_sent':
                acknowledged.append(args)
                self.assertEqual(embed_marker(self.messages[0].embeds[0]), marker('audit:stripped-url'))
            return await real_db(method, *args, **kwargs)
        with patch.object(self.audit, 'db', side_effect=db):
            await self.audit.flush_once()
        self.channel.send.assert_awaited_once()
        self.messages[0].edit.assert_awaited()
        self.assertTrue(acknowledged)
        self.assertIn(marker('audit:stripped-url'), self.messages[0].embeds[0].footer.text)
        self.assertEqual(self.audit.store.stats()['pending'], 0)
        self.assertEqual(self.audit.store.get('audit:stripped-url')['message_id'], '9103')

    async def test_recovery_requires_bot_author_and_all_exact_markers(self):
        await self.queue('audit:a')
        await self.queue('audit:b')
        self.audit.store.reserve(['audit:a', 'audit:b'], 'recover-batch', self.when.isoformat())
        rows = self.audit.store.batch('recover-batch')
        valid = self.audit.embeds(rows)
        self.messages.extend([self.message(1, valid, author=123), self.message(2, valid[:1])])
        self.assertIsNone(await self.audit.recover(self.channel, rows))
        genuine = self.message(3, valid)
        self.messages.append(genuine)
        self.assertIs(await self.audit.recover(self.channel, rows), genuine)

    async def test_merged_entry_updates_original_batch_without_duplicate_messages(self):
        await self.queue('audit:one')
        await self.queue('audit:two')
        await self.audit.flush_once()
        previous_id = self.messages[0].id
        changed = self.embed('Miembros movidos en voz')
        changed.add_field(name='Cantidad acumulada', value='4')
        await self.audit.publish('audit:one', changed, event_type='audit', event_time=self.when)
        await self.audit.flush_once()
        self.channel.send.assert_awaited_once()
        self.messages[0].edit.assert_awaited_once()
        self.assertEqual(len(self.messages[0].embeds), 2)
        self.assertEqual(self.audit.store.get('audit:one')['message_id'], str(previous_id))
        self.assertEqual(self.audit.store.get('audit:one')['historical'], 1)
        self.assertEqual(self.audit.store.stats()['pending'], 0)

    async def test_large_merged_fields_are_compacted_without_blocking_queue_or_losing_ids(self):
        for i in range(5):
            await self.queue(f'audit:{i}')
        await self.audit.flush_once()
        originals = {}
        for i in range(5):
            e = self.embed(f'Canal actualizado {i}', size=0)
            for n in range(4):
                e.add_field(name=f'Cambio {n}', value='X' * 1024)
            originals[f'audit:{i}'] = e
            await self.audit.publish(f'audit:{i}', e, event_type='audit', event_time=self.when)
        await self.audit.flush_once()
        shown = self.messages[0].embeds
        self.assertLessEqual(sum(len(e) for e in shown), 5900)
        self.assertEqual(len(shown), 5)
        for i, e in enumerate(shown):
            self.assertEqual(e.title, f'Canal actualizado {i}')
            self.assertEqual(e.timestamp, self.when)
            self.assertIn('Detalles abreviados', e.description)
            self.assertEqual(embed_marker(e), marker(f'audit:{i}'))
            fields = {field.name: field.value for field in e.fields}
            self.assertEqual(fields['Responsable'], f'<@{OWNER_ID}>')
            self.assertIn(str(OWNER_ID), fields['IDs'])
            self.assertIn('X' * 1024, self.audit.store.get(f'audit:{i}')['payload_json'])
        self.assertFalse(await self.audit.flush_once())
        self.channel.send.assert_awaited_once()

    async def test_gateway_is_guild_scoped_deduplicated_and_does_not_advance_poll_cursor(self):
        entry = NS(guild=self.guild, id=1572621740033446082, created_at=self.when)
        with patch('vice_audit.format_audit_entry', return_value=self.embed()):
            await self.audit.entry_create(entry)
            await self.audit.entry_create(entry)
            await self.audit.entry_create(NS(guild=NS(id=123), id=1))
        self.assertEqual(self.audit.store.stats()['total'], 1)
        self.assertIsNone(self.audit.store.state('cursor'))
        self.channel.send.assert_not_awaited()

    async def test_scan_imports_all_oldest_first_then_polls_overlap_and_keeps_original_history(self):
        entries = [NS(guild=self.guild, id=1572621740033446082 + i, created_at=self.when)
                   for i in range(105)]
        async def audit_logs(**kwargs):
            for entry in entries:
                yield entry
        self.guild.audit_logs = MagicMock(side_effect=audit_logs)
        with patch('vice_audit.format_audit_entry', return_value=self.embed()):
            self.assertEqual(await self.audit.scan(full=True), 105)
            first = self.guild.audit_logs.call_args.kwargs
            self.assertIsNone(first['limit'])
            self.assertTrue(first['oldest_first'])
            self.assertEqual(first['after'].id, 0)
            await self.audit.scan()
        second = self.guild.audit_logs.call_args.kwargs
        self.assertGreater(second['after'].id, 0)
        self.assertLess(second['after'].id, entries[-1].id)
        self.assertEqual(self.audit.store.state('cursor'), entries[-1].id)
        self.assertEqual(self.audit.store.stats()['total'], 105)
        self.assertTrue(all(row['historical'] for row in self.audit.store.pending(200)))
        self.assertIsNotNone(self.audit.store.state('last_full_scan'))


if __name__ == '__main__':
    unittest.main()
