"""Audit format refreshes preserve real messages and journal their prior cards."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from vice_audit import ViceAudit
from vice_design import GUILD_ID, BOT_ID, OWNER_ID


class GuildAuditRefreshTests(unittest.IsolatedAsyncioTestCase):
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
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild = 7001, self.guild
        self.channel.overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.guild.me: discord.PermissionOverwrite(view_channel=True),
        }
        self.channel.overwrites_for.side_effect = lambda target: self.channel.overwrites.get(
            target, discord.PermissionOverwrite())
        self.channel.permissions_for.return_value = discord.Permissions(
            view_channel=True, send_messages=True, embed_links=True, read_message_history=True)
        self.values = {'channel:log': self.channel.id, 'role:founder': 11,
                       'role:admin': 12, 'role:mod': 13, 'role:support': 14}
        self.messages, self.snapshots = [], []

        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')

        async def track(kind, title, operation, request, snapshot=None):
            self.snapshots.append(await snapshot())
            return await operation()

        self.system = NS(
            path=Path(self.tmp.name) / 'vice.sqlite3',
            bot=NS(user=NS(id=BOT_ID), get_guild=MagicMock(return_value=self.guild)),
            validate_guild=validate, channel=lambda guild, key: self.channel,
            channel_id=lambda key: self.values.get('channel:' + key),
            store=NS(get=self.values.get), track=AsyncMock(side_effect=track), panel=AsyncMock())
        self.audit = ViceAudit(self.system)
        await self.audit.start()
        self.addAsyncCleanup(self.audit.close)
        self.when = datetime(2026, 11, 18, 20, 57, tzinfo=timezone.utc)

        async def send(**kwargs):
            message = NS(id=9000 + len(self.messages), author=NS(id=BOT_ID),
                         content='', attachments=[], components=[],
                         embeds=[discord.Embed.from_dict(e.to_dict()) for e in kwargs['embeds']])

            async def edit(**changes):
                message.embeds = [discord.Embed.from_dict(e.to_dict()) for e in changes['embeds']]
                return message

            message.edit = AsyncMock(side_effect=edit)
            self.messages.append(message)
            return message

        async def fetch(message_id):
            return next(message for message in self.messages if message.id == message_id)

        self.channel.send = AsyncMock(side_effect=send)
        self.channel.fetch_message = AsyncMock(side_effect=fetch)

    def card(self, description):
        card = discord.Embed(description=description, timestamp=self.when, color=0xFFB44B)
        card.set_author(name='esschino')
        card.set_footer(text='VIce District • 18/11 16:57 AST')
        card.add_field(name='IDs', value=f'Usuario `{OWNER_ID}` · Servidor `{GUILD_ID}`')
        return card

    async def publish(self, key, description, historical=True):
        await self.audit.publish(key, self.card(description), event_type='audit',
                                 event_time=self.when, source_id=key.split(':')[-1],
                                 historical=historical)

    async def changed_existing(self):
        key = 'audit:1572710000000000001'
        await self.publish(key, f'<@{OWNER_ID}> actualizó el servidor.')
        await self.audit.flush_once()
        message = self.messages[0]
        before = deepcopy([embed.to_dict() for embed in message.embeds])
        await self.publish(key, f'<@{OWNER_ID}> cambió el **fondo de invitación**.')
        return key, message, before

    async def test_full_reingest_edits_same_batch_and_keeps_unchanged_card(self):
        entries = [NS(guild=self.guild, id=1572710000000000001 + i, created_at=self.when)
                   for i in range(2)]
        original_cards = {
            entries[0].id: self.card(f'<@{OWNER_ID}> actualizó el servidor.'),
            entries[1].id: self.card(f'<@{OWNER_ID}> creó un canal.'),
        }
        with patch('vice_audit.format_audit_entry', side_effect=lambda entry, **kw: original_cards[entry.id]):
            for entry in entries:
                await self.audit.ingest(entry, historical=True)
        await self.audit.flush_once()
        message = self.messages[0]
        original_id = message.id
        unchanged = deepcopy(message.embeds[1].to_dict())
        updated_cards = dict(original_cards)
        updated_cards[entries[0].id] = self.card(f'<@{OWNER_ID}> cambió el **fondo de invitación**.')

        async def audit_logs(**kwargs):
            for entry in entries:
                yield entry

        self.guild.audit_logs = MagicMock(side_effect=audit_logs)
        with patch('vice_audit.format_audit_entry', side_effect=lambda entry, **kw: updated_cards[entry.id]):
            self.assertEqual(await self.audit.scan(full=True), 2)
            self.assertTrue(await self.audit.flush_once())
            self.assertEqual(await self.audit.scan(full=True), 2)
            self.assertFalse(await self.audit.flush_once())

        self.channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        self.assertEqual(message.id, original_id)
        self.assertEqual(len(message.embeds), 2)
        self.assertEqual(message.embeds[1].to_dict(), unchanged)
        self.assertIn('fondo de invitación', message.embeds[0].description)
        for entry in entries:
            row = self.audit.store.get('audit:' + str(entry.id))
            self.assertEqual(row['message_id'], str(original_id))
            self.assertEqual(row['event_time'], self.when.isoformat())
            self.assertEqual(row['historical'], 1)
            self.assertEqual(row['fingerprint'], row['sent_fingerprint'])
        self.assertEqual(self.audit.store.stats()['total'], 2)

    async def test_edit_journals_complete_immutable_prior_card_before_mutation(self):
        key, message, before = await self.changed_existing()
        self.snapshots.clear()
        await self.audit.flush_once()
        self.assertEqual(len(self.snapshots), 1)
        previous = self.snapshots[0]['before_message']
        self.assertEqual(previous['id'], message.id)
        self.assertEqual(previous['author'], BOT_ID)
        self.assertEqual(previous['content'], '')
        self.assertEqual(previous['attachments'], [])
        self.assertEqual(previous['components'], [])
        self.assertEqual(previous['embeds'], before)
        self.assertNotEqual(previous['embeds'], [embed.to_dict() for embed in message.embeds])
        self.assertEqual(self.audit.store.get(key)['message_id'], str(message.id))

    async def test_existing_message_with_wrong_marker_is_not_edited(self):
        key, message, _ = await self.changed_existing()
        message.embeds[0].url = (
            f'https://discord.com/channels/{GUILD_ID}/{self.channel.id}?ref=' + '0' * 20)
        self.system.track.reset_mock()
        with self.assertRaises(ValueError):
            await self.audit.flush_once()
        message.edit.assert_not_awaited()
        self.system.track.assert_not_awaited()
        self.assertEqual(self.audit.store.stats()['pending'], 1)
        self.assertNotEqual(self.audit.store.get(key)['fingerprint'],
                            self.audit.store.get(key)['sent_fingerprint'])

    async def test_existing_message_with_extra_embed_is_not_edited(self):
        _, message, _ = await self.changed_existing()
        message.embeds.append(discord.Embed(description='Another bot feature'))
        with self.assertRaises(ValueError):
            await self.audit.flush_once()
        message.edit.assert_not_awaited()
        self.assertEqual(self.audit.store.stats()['pending'], 1)

    async def test_other_message_content_attachments_or_components_are_not_overwritten(self):
        _, message, _ = await self.changed_existing()
        cases = [('content', 'A separate note'),
                 ('attachments', [NS(id=100, filename='original.txt')]),
                 ('components', [NS(type=1)])]
        for attribute, value in cases:
            with self.subTest(attribute=attribute):
                setattr(message, attribute, value)
                with self.assertRaises(ValueError):
                    await self.audit.flush_once()
                message.edit.assert_not_awaited()
                setattr(message, attribute, '' if attribute == 'content' else [])
        self.assertEqual(self.audit.store.stats()['pending'], 1)

    async def test_existing_message_from_other_author_is_not_edited(self):
        _, message, _ = await self.changed_existing()
        message.author.id = OWNER_ID
        with self.assertRaises(ValueError):
            await self.audit.flush_once()
        message.edit.assert_not_awaited()
        self.assertEqual(self.audit.store.stats()['pending'], 1)


if __name__ == '__main__':
    unittest.main()
