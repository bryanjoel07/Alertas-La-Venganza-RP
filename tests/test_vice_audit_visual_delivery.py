"""Visual audit delivery preserves registered messages, files and event identity."""
from copy import deepcopy
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from vice_audit import ViceAudit, semantic_embeds
from vice_design import GUILD_ID, BOT_ID, OWNER_ID


class AuditVisualDeliveryTests(unittest.IsolatedAsyncioTestCase):
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
            view_channel=True, send_messages=True, embed_links=True, read_message_history=True,
            attach_files=True)
        self.values = {'channel:log': self.channel.id, 'role:founder': 11,
                       'role:admin': 12, 'role:mod': 13, 'role:support': 14}
        self.messages, self.snapshots, self.registry = [], [], {}
        self.next_attachment = 10000

        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')

        async def track(kind, title, operation, request, snapshot=None):
            self.snapshots.append(deepcopy(await snapshot()))
            return await operation()

        self.system = NS(
            path=Path(self.tmp.name) / 'vice.sqlite3',
            bot=NS(user=NS(id=BOT_ID), get_guild=MagicMock(return_value=self.guild)),
            validate_guild=validate, channel=lambda guild, key: self.channel,
            channel_id=lambda key: self.values.get('channel:' + key),
            store=NS(get=self.values.get), track=AsyncMock(side_effect=track), panel=AsyncMock())
        self.audit = ViceAudit(self.system)

        async def files_for(embeds):
            files = []
            for embed in embeds:
                url = str(embed.image.url or '')
                if url.startswith('attachment://'):
                    filename = url.removeprefix('attachment://')
                    files.append(discord.File(io.BytesIO(self.registry[filename][1]), filename=filename))
            return files

        async def validate_attachments(attachments, rows):
            keys = {row['key'] for row in rows}
            for attachment in attachments:
                registered = self.registry.get(attachment.filename)
                if not registered or registered[0] not in keys or attachment.size != len(registered[1]):
                    return False
            return True

        self.audit.visuals = NS(start=AsyncMock(), render=AsyncMock(return_value=None),
                               files_for=AsyncMock(side_effect=files_for),
                               validate_attachments=AsyncMock(side_effect=validate_attachments))
        await self.audit.start()
        self.addAsyncCleanup(self.audit.close)
        self.when = datetime(2026, 11, 18, 20, 57, tzinfo=timezone.utc)

        async def send(**kwargs):
            message = NS(id=9000 + len(self.messages), author=NS(id=BOT_ID),
                         content='', attachments=[], components=[], embeds=[])

            async def edit(**changes):
                self.apply_payload(message, changes)
                return message

            message.edit = AsyncMock(side_effect=edit)
            self.apply_payload(message, kwargs)
            self.messages.append(message)
            return message

        async def fetch(message_id):
            return next(message for message in self.messages if message.id == message_id)

        async def history(**kwargs):
            for message in self.messages:
                yield message

        self.channel.send = AsyncMock(side_effect=send)
        self.channel.fetch_message = AsyncMock(side_effect=fetch)
        self.channel.history = MagicMock(side_effect=history)

    def apply_payload(self, message, payload):
        supplied = payload.get('attachments', payload.get('files'))
        if supplied is not None:
            attachments = []
            for value in supplied:
                if isinstance(value, discord.File):
                    self.next_attachment += 1
                    data = value.fp.getvalue()
                    attachment = NS(id=self.next_attachment, filename=value.filename,
                                    size=len(data), description=None)
                    attachment.url = (f'https://cdn.discordapp.com/attachments/{self.channel.id}/'
                                      f'{attachment.id}/{attachment.filename}?ex=123&is=456&hm=signature')
                    attachment.proxy_url = attachment.url.replace('cdn.discordapp.com', 'media.discordapp.net')
                    attachment.to_dict = lambda a=attachment: dict(
                        id=a.id, filename=a.filename, size=a.size, url=a.url, proxy_url=a.proxy_url)
                    attachments.append(attachment)
                else:
                    attachments.append(value)
            message.attachments = attachments
        by_name = {item.filename: item for item in message.attachments}
        message.embeds = []
        for embed in payload['embeds']:
            data = deepcopy(embed.to_dict())
            url = data.get('image', {}).get('url', '')
            if url.startswith('attachment://'):
                attachment = by_name[url.removeprefix('attachment://')]
                data['image'] = dict(url=attachment.url, proxy_url=attachment.proxy_url,
                                     width=960, height=320)
            message.embeds.append(discord.Embed.from_dict(data))

    def card(self, description='Un cambio real'):
        result = discord.Embed(description=description, timestamp=self.when, color=0xFFB44B)
        result.set_author(name='esschino')
        result.set_footer(text='VIce District • 18/11 16:57 AST')
        return result

    def register(self, key, filename):
        self.registry[filename] = (key, b'cached-report-' + filename.encode())
        return self.card().set_image(url='attachment://' + filename)

    async def publish(self, key, card):
        await self.audit.publish(key, card, event_type='audit', event_time=self.when,
                                 source_id=key.split(':')[-1], historical=True)

    async def test_ingest_attaches_registered_comparison_without_changing_event_time(self):
        entry = NS(id=1572718032730464406, guild=self.guild, created_at=self.when)
        filename = 'vice-audit-comparison-first.jpg'
        self.audit.visuals.render.return_value = filename
        self.registry[filename] = ('audit:' + str(entry.id), b'cached-image')
        with patch('vice_audit.format_audit_entry', return_value=self.card()):
            await self.audit.ingest(entry)
        self.audit.visuals.render.assert_awaited_once_with(entry)
        row = self.audit.store.get('audit:' + str(entry.id))
        embed = self.audit.embeds([row])[0]
        self.assertEqual(embed.image.url, 'attachment://' + filename)
        self.assertEqual(embed.timestamp, self.when)
        self.assertEqual(row['source_id'], str(entry.id))

    async def test_refresh_adds_image_in_place_then_journals_existing_attachment(self):
        key, filename = 'audit:1572718032730464406', 'vice-audit-comparison-first.jpg'
        await self.publish(key, self.card('Antes del cambio de formato'))
        await self.audit.flush_once()
        message = self.messages[0]
        original_id = message.id
        card = self.register(key, filename)
        await self.publish(key, card)
        await self.audit.flush_once()
        self.assertEqual(message.id, original_id)
        self.assertEqual(message.embeds[0].timestamp, self.when)
        self.assertEqual([item.filename for item in message.attachments], [filename])
        self.channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        self.assertEqual(self.snapshots[-1]['before_message']['attachments'], [])
        prior_attachment = message.attachments[0]
        prior_id, prior_url = prior_attachment.id, prior_attachment.url

        card.description = 'Descripción actualizada, misma comparación'
        await self.publish(key, card)
        await self.audit.flush_once()
        self.assertEqual(message.id, original_id)
        self.audit.visuals.validate_attachments.assert_awaited()
        snapshot = self.snapshots[-1]['before_message']['attachments']
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(str(snapshot[0]['id']), str(prior_id))
        self.assertEqual(snapshot[0]['filename'], filename)
        self.assertEqual(snapshot[0]['size'], len(self.registry[filename][1]))
        self.assertEqual(snapshot[0]['url'], prior_url)
        self.assertFalse(await self.audit.flush_once())
        self.assertEqual(message.edit.await_count, 2)
        self.channel.send.assert_awaited_once()

    async def test_historical_batch_includes_every_registered_image_without_spurious_edit(self):
        names = ['vice-audit-one.jpg', 'vice-audit-two.jpg']
        for index, filename in enumerate(names):
            key = 'audit:' + str(1572718032730464406 + index)
            await self.publish(key, self.register(key, filename))
        await self.audit.flush_once()
        self.assertEqual(len(self.messages), 1)
        message = self.messages[0]
        self.assertEqual(len(message.embeds), 2)
        self.assertEqual([attachment.filename for attachment in message.attachments], names)
        message.edit.assert_not_awaited()
        self.assertFalse(await self.audit.flush_once())
        self.assertEqual(self.audit.store.stats()['pending'], 0)

    async def test_unregistered_attachment_blocks_edit_and_preserves_pending_event(self):
        key, filename = 'audit:1572718032730464406', 'vice-audit-registered.jpg'
        await self.publish(key, self.register(key, filename))
        await self.audit.flush_once()
        message = self.messages[0]
        message.attachments.append(NS(id=20000, filename='unrelated.txt', size=20))
        card = self.register(key, filename)
        card.description = 'An updated event'
        await self.publish(key, card)
        with self.assertRaises(ValueError):
            await self.audit.flush_once()
        message.edit.assert_not_awaited()
        self.assertEqual(self.audit.store.stats()['pending'], 1)

    async def test_attachment_registered_for_different_event_is_not_repurposed(self):
        key, filename = 'audit:1572718032730464406', 'vice-audit-registered.jpg'
        await self.publish(key, self.register(key, filename))
        await self.audit.flush_once()
        message = self.messages[0]
        self.registry[filename] = ('audit:another-event', self.registry[filename][1])
        card = self.card('An updated event').set_image(url='attachment://' + filename)
        await self.publish(key, card)
        with self.assertRaises(ValueError):
            await self.audit.flush_once()
        message.edit.assert_not_awaited()
        self.assertEqual(self.audit.store.stats()['pending'], 1)

    async def test_nonce_correction_rejects_foreign_or_unverifiable_response_without_edit(self):
        key, filename = 'audit:1572718032730464406', 'vice-audit-registered.jpg'
        await self.publish(key, self.register(key, filename))
        desired = self.audit.embeds([self.audit.store.get(key)])[0]
        for failure in ('author', 'content', 'components', 'attachment', 'foreign_marker', 'missing_marker'):
            with self.subTest(failure=failure):
                old = discord.Embed.from_dict(deepcopy(desired.to_dict()))
                old.description = 'An older response which would otherwise be edited'
                message = NS(id=9100, author=NS(id=BOT_ID), content='', components=[],
                             attachments=[], embeds=[old], edit=AsyncMock())
                if failure == 'author':
                    message.author.id = OWNER_ID
                elif failure == 'content':
                    message.content = 'Unrelated content'
                elif failure == 'components':
                    message.components = [NS(type=1)]
                elif failure == 'attachment':
                    message.attachments = [NS(id=20000, filename='unrelated.txt', size=20)]
                elif failure == 'foreign_marker':
                    old.url = f'https://discord.com/channels/{GUILD_ID}/7001?ref=' + 'f' * 20
                else:
                    old.url = None
                self.channel.send.side_effect = None
                self.channel.send.return_value = message
                with self.assertRaises(ValueError):
                    await self.audit.flush_once()
                message.edit.assert_not_awaited()
                self.assertEqual(self.audit.store.stats()['pending'], 1)

    async def test_nonce_correction_journals_prior_registered_image_before_edit(self):
        key = 'audit:1572718032730464406'
        old_name, new_name = 'vice-audit-older.jpg', 'vice-audit-newer.jpg'
        await self.publish(key, self.register(key, old_name))
        old_embeds = self.audit.embeds([self.audit.store.get(key)])
        files = await self.audit.visuals.files_for(old_embeds)
        try:
            previous = await self.channel.send(embeds=old_embeds, files=files)
        finally:
            for file in files:
                file.close()
        old_attachment = previous.attachments[0]
        card = self.register(key, new_name)
        card.description = 'Newer source, same recorded event'
        await self.publish(key, card)
        self.channel.send.reset_mock()
        self.channel.send.side_effect = None
        self.channel.send.return_value = previous
        await self.audit.flush_once()
        previous.edit.assert_awaited_once()
        self.assertEqual([a.filename for a in previous.attachments], [new_name])
        correction = next(s for s in self.snapshots if 'current_message' in s)
        self.assertEqual(correction['before_message']['id'], previous.id)
        self.assertEqual(correction['before_message']['attachments'][0]['url'], old_attachment.url)
        self.assertEqual(correction['before_message']['attachments'][0]['filename'], old_name)
        self.assertEqual(self.audit.store.get(key)['message_id'], str(previous.id))
        self.assertEqual(self.audit.store.stats()['pending'], 0)

    async def test_stripped_url_with_exact_image_body_is_journaled_and_recovers_footer(self):
        key, filename = 'audit:1572718032730464406', 'vice-audit-comparison.jpg'
        await self.publish(key, self.register(key, filename))
        original_send = self.channel.send.side_effect
        async def stripped_send(**kwargs):
            message = await original_send(**kwargs)
            for card in message.embeds:
                card.url = None
            original_edit = message.edit.side_effect
            async def stripped_edit(**changes):
                result = await original_edit(**changes)
                for card in result.embeds:
                    card.url = None
                return result
            message.edit.side_effect = stripped_edit
            return message
        self.channel.send.side_effect = stripped_send
        await self.audit.flush_once()
        message = self.messages[0]
        message.edit.assert_awaited_once()
        self.assertIn('ref:', message.embeds[0].footer.text)
        correction = next(s for s in self.snapshots if 'current_message' in s)
        self.assertEqual(correction['before_message']['attachments'][0]['filename'], filename)
        self.assertEqual(self.audit.store.stats()['pending'], 0)

    async def test_attach_files_permission_is_required_only_for_visual_delivery(self):
        self.channel.permissions_for.return_value.attach_files = False
        await self.publish('audit:1572718032730464406', self.card())
        await self.audit.flush_once()
        self.channel.send.assert_awaited_once()
        key = 'audit:1572718032730464407'
        await self.publish(key, self.register(key, 'vice-audit-new.jpg'))
        with self.assertRaisesRegex(ValueError, 'Adjuntar archivos'):
            await self.audit.flush_once()
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.audit.store.stats()['pending'], 1)

    async def test_attach_files_permission_is_checked_before_editing_existing_card(self):
        key = 'audit:1572718032730464406'
        card = self.register(key, 'vice-audit-comparison.jpg')
        await self.publish(key, card)
        await self.audit.flush_once()
        self.channel.permissions_for.return_value.attach_files = False
        card.description = 'Updated text which still needs the registered image'
        await self.publish(key, card)
        with self.assertRaisesRegex(ValueError, 'Adjuntar archivos'):
            await self.audit.flush_once()
        self.messages[0].edit.assert_not_awaited()
        self.assertEqual(self.audit.store.stats()['pending'], 1)

    def test_semantics_normalize_only_evidenced_attachment_url_not_arbitrary_cdn_image(self):
        filename, identifier = 'vice-audit-image.jpg', 1234567
        url = f'https://cdn.discordapp.com/attachments/7001/{identifier}/{filename}?ex=1&hm=signed'
        attachment = NS(id=identifier, filename=filename, url=url,
                        proxy_url=url.replace('cdn.discordapp.com', 'media.discordapp.net'))
        desired = self.card().set_image(url='attachment://' + filename)
        actual = self.card().set_image(url=url)
        self.assertEqual(semantic_embeds([actual], attachments=[attachment]), semantic_embeds([desired]))
        self.assertNotEqual(semantic_embeds([actual]), semantic_embeds([desired]))
        unrelated = self.card().set_image(url=url.replace(str(identifier), '9999999'))
        self.assertNotEqual(semantic_embeds([unrelated], attachments=[attachment]), semantic_embeds([desired]))


if __name__ == '__main__':
    unittest.main()
