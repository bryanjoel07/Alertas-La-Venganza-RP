import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import zipfile

import discord

from esschino import StudioStore
from vice_design import GUILD_ID, BOT_ID, OWNER_ID
from vice_ticket_archive import (TicketArchive, DESTINATION_KEY, MAX_ATTACHMENT, TOPIC,
                                PUBLICATION_VERSION, LEGACY_WRITE_GAPS, sha_file)


async def values(items):
    for item in items:
        yield item


class TicketArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StudioStore(Path(self.tmp.name) / 'vice.sqlite3')
        self.store.initialize()
        for key, value in [('category:team', 80), ('category:closed', 88),
                           ('role:admin', 11), ('role:mod', 12), ('role:support', 13)]:
            self.store.put(key, value)
        self.store.add_ticket(55, 999, 'report')
        self.store.ticket_state(55, 'closed')
        self.row = self.store.ticket(55)
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id, self.guild.filesize_limit = GUILD_ID, OWNER_ID, 10 * 1024 * 1024
        self.roles = {}
        for role_id in [GUILD_ID, 11, 12, 13]:
            role = MagicMock(spec=discord.Role)
            role.id = role_id
            self.roles[role_id] = role
        self.guild.default_role = self.roles[GUILD_ID]
        self.guild.get_role.side_effect = self.roles.get
        self.owner = MagicMock(spec=discord.Member)
        self.owner.id = OWNER_ID
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id = BOT_ID
        self.guild.get_member.side_effect = lambda value: self.owner if value == OWNER_ID else None
        self.category = MagicMock(spec=discord.CategoryChannel)
        self.category.id, self.category.guild, self.category.position = 80, self.guild, 10
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild, self.channel.category_id = 55, self.guild, 88
        self.channel.name, self.channel.topic = 'cerrado-999', 'VIce ticket closed owner=999'
        self.channel.threads = []
        self.channel.archived_threads.side_effect = lambda **kwargs: values([])
        self.messages = [self.message(101, '<script>alert("unsafe")</script>')]
        self.channel.history.side_effect = lambda **kwargs: values(list(self.messages))
        self.destination = MagicMock(spec=discord.TextChannel)
        self.destination.id, self.destination.guild, self.destination.category_id = 70, self.guild, 80
        self.destination.topic = TOPIC
        self.channels = {55: self.channel, 70: self.destination, 80: self.category}
        self.guild.fetch_channel = AsyncMock(side_effect=lambda key: self.channels[key])
        self.guild.fetch_channels = AsyncMock(return_value=list(self.channels.values()))
        self.entries = []
        self.guild.audit_logs.side_effect = lambda **kwargs: values(self.entries)
        self.bot = NS(user=NS(id=BOT_ID), get_guild=Mock(return_value=self.guild),
                      intents=NS(message_content=True))
        self.states = []
        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')
        async def call(method, *args):
            return getattr(self.store, method)(*args)
        async def track(kind, title, operation, request, snapshot=None):
            self.states.append(await snapshot())
            return await operation()
        self.system = NS(path=self.store.path, store=self.store, bot=self.bot,
            validate_guild=validate, call=AsyncMock(side_effect=call), track=AsyncMock(side_effect=track))
        self.archive = TicketArchive(self.system)
        await self.archive.start()
        self.destination.overwrites = self.archive.overwrites(self.guild)
        self.store.put(DESTINATION_KEY, dict(guild=GUILD_ID, channel=70, nonce='setup'))
        self.uploads, self.bytes = [], {}
        self.destination.history.side_effect = lambda **kwargs: values(list(self.uploads))
        self.destination.fetch_message = AsyncMock(side_effect=lambda key: next(m for m in self.uploads if m.id == key))
        async def send(**kwargs):
            upload = kwargs['file']
            body = upload.fp.read()
            url = f'https://cdn.discordapp.com/attachments/70/{200 + len(self.uploads)}/backup.zip'
            self.bytes[url] = body
            message = NS(id=200 + len(self.uploads), author=NS(id=BOT_ID), content='',
                embeds=[kwargs['embed']], attachments=[NS(filename=upload.filename, size=len(body), url=url)])
            self.uploads.append(message)
            return message
        self.destination.send = AsyncMock(side_effect=send)
        async def download(url, path, expected, maximum):
            body = self.bytes[url]
            if len(body) != expected or len(body) > maximum:
                raise ValueError('incomplete')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            return hashlib.sha256(body).hexdigest()
        self.archive.download = AsyncMock(side_effect=download)

    def message(self, message_id, content, attachments=()):
        return NS(id=message_id, content=content, author=NS(id=999, name='user',
            display_name='Usuario <script>', bot=False, display_avatar=None),
            created_at=datetime(2026, 11, 18, tzinfo=timezone.utc), edited_at=None,
            type=discord.MessageType.default, pinned=False, flags=discord.MessageFlags(),
            reference=None, attachments=list(attachments), embeds=[], components=[], stickers=[])

    async def test_zip_has_escaped_html_full_json_assignment_and_attachment_bytes(self):
        attachment = NS(id=301, filename='../../evil<script>.txt', size=5, content_type='text/plain',
            url='https://cdn.discordapp.com/attachments/55/301/file.txt?ex=old', width=None, height=None)
        self.bytes[attachment.url] = b'hello'
        self.messages[0].attachments.append(attachment)
        self.store.put('ticket_assignment:55', dict(staff_id=77, staff_name='Moderación'))
        receipt = await self.archive.backup(self.channel, self.row, 77)
        self.assertEqual(receipt['state'], 'verified')
        self.assertEqual(receipt['attachment_count'], 1)
        path = self.archive.root / receipt['filename']
        self.assertEqual(sha_file(path), receipt['sha256'])
        with zipfile.ZipFile(path) as archive:
            self.assertTrue(all(not name.startswith('/') and '..' not in name.split('/') for name in archive.namelist()))
            html = archive.read('transcript.html').decode()
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;script&gt;', html)
            data = json.loads(archive.read('transcript.json'))
            self.assertEqual(data['ticket']['kind'], 'report')
            self.assertEqual(data['assignment']['staff_id'], 77)
            self.assertEqual(data['messages'][0]['content'], '<script>alert("unsafe")</script>')
            name = data['messages'][0]['attachments'][0]['archive_path']
            self.assertEqual(archive.read(name), b'hello')
        self.assertTrue(self.states)

    async def test_repeat_and_restart_reuse_exact_verified_copy(self):
        first = await self.archive.backup(self.channel, self.row, 77)
        # Even losing the local ZIP must not cause a second Discord copy.
        (self.archive.root / first['filename']).unlink()
        restarted = TicketArchive(self.system)
        restarted.download = self.archive.download
        second = await restarted.backup(self.channel, self.row, 77)
        self.assertEqual(first['message_id'], second['message_id'])
        self.destination.send.assert_awaited_once()

    async def test_missing_content_intent_cannot_claim_complete_backup(self):
        self.bot.intents.message_content = False
        with self.assertRaisesRegex(ValueError, 'contenido completo'):
            await self.archive.backup(self.channel, self.row, 77)
        self.channel.history.assert_not_called()
        self.destination.send.assert_not_awaited()

    async def test_panel_identifies_uncached_owner_and_assigned_staff_without_ping(self):
        self.guild.get_member.side_effect = lambda member_id: None
        self.store.put('ticket_assignment:55', dict(staff_id=77))
        await self.archive.backup(self.channel, self.row, 77)
        fields = {field.name: field.value for field in self.uploads[0].embeds[0].fields}
        self.assertEqual(fields['Autor'], '<@999>')
        self.assertEqual(fields['Responsable'], '<@77>')
        self.assertEqual(fields['Categoría'], 'Reportar a un jugador')
        mentions = self.destination.send.await_args.kwargs['allowed_mentions'].to_dict()
        self.assertEqual(mentions['parse'], [])

    async def test_crash_after_send_recovers_exact_marker_without_second_upload(self):
        original = self.destination.send.side_effect
        async def crashing(**kwargs):
            await original(**kwargs)
            raise OSError('connection lost after Discord accepted upload')
        self.destination.send.side_effect = crashing
        with self.assertRaises(OSError):
            await self.archive.backup(self.channel, self.row, 77)
        self.assertEqual(len(self.uploads), 1)
        self.destination.send.side_effect = original
        receipt = await self.archive.backup(self.channel, self.row, 77)
        self.assertEqual(receipt['message_id'], self.uploads[0].id)
        self.destination.send.assert_awaited_once()

    async def test_changed_transcript_after_upload_keeps_channel_and_reports_change(self):
        original = self.destination.send.side_effect
        async def changed(**kwargs):
            message = await original(**kwargs)
            self.messages[0].content = 'edit after capture'
            return message
        self.destination.send.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'cambió'):
            await self.archive.backup(self.channel, self.row, 77)
        self.assertEqual(self.store.ticket(55)['state'], 'closed')

    async def test_public_or_extra_member_destination_never_receives_transcript(self):
        self.destination.overwrites[self.guild.default_role].view_channel = True
        with self.assertRaises(ValueError):
            await self.archive.backup(self.channel, self.row, 77)
        self.destination.send.assert_not_awaited()
        self.destination.overwrites = self.archive.overwrites(self.guild)
        outsider = MagicMock(spec=discord.Member)
        outsider.id = 999
        self.destination.overwrites[outsider] = discord.PermissionOverwrite(view_channel=True)
        with self.assertRaises(ValueError):
            await self.archive.backup(self.channel, self.row, 77)
        self.destination.send.assert_not_awaited()

    async def test_oversized_attachment_or_upload_fails_without_sending(self):
        self.messages[0].attachments.append(NS(id=300, size=MAX_ATTACHMENT + 1))
        with self.assertRaisesRegex(ValueError, '25 MiB'):
            await self.archive.backup(self.channel, self.row, 77)
        self.destination.send.assert_not_awaited()
        self.messages[0].attachments.clear()
        self.guild.filesize_limit = 65537
        with self.assertRaisesRegex(ValueError, 'límite'):
            await self.archive.backup(self.channel, self.row, 77)
        self.destination.send.assert_not_awaited()

    async def test_remote_hash_mismatch_is_not_verified(self):
        original = self.archive.download.side_effect
        async def corrupt(url, path, expected, maximum):
            await original(url, path, expected, maximum)
            return '0' * 64
        self.archive.download.side_effect = corrupt
        with self.assertRaisesRegex(ValueError, 'no coincide'):
            await self.archive.backup(self.channel, self.row, 77)
        self.assertEqual(self.store.ticket(55)['state'], 'closed')

    async def test_scope_open_threads_and_category_mismatch_are_rejected(self):
        self.store.ticket_state(55, 'open')
        with self.assertRaises(ValueError):
            await self.archive.backup(self.channel, self.row, 77)
        self.store.ticket_state(55, 'closed')
        self.channel.threads = [NS(id=123)]
        with self.assertRaisesRegex(ValueError, 'hilos'):
            await self.archive.backup(self.channel, self.row, 77)
        self.channel.threads = []
        self.channel.category_id = 99
        with self.assertRaises(ValueError):
            await self.archive.backup(self.channel, self.row, 77)
        self.destination.send.assert_not_awaited()

    async def test_destination_recovery_requires_exact_bot_creation_audit_reason(self):
        self.store.put(DESTINATION_KEY, dict(guild=GUILD_ID, nonce='private-nonce',
            started_at=datetime.now(timezone.utc).isoformat(), attempted_at='prior-attempt'))
        self.guild.create_text_channel = AsyncMock()
        with self.assertRaisesRegex(ValueError, 'No se creará otro'):
            await self.archive.ready()
        self.guild.create_text_channel.assert_not_awaited()
        self.entries = [NS(user=NS(id=BOT_ID), reason='VIce ticket archive private-nonce',
                           target=NS(id=70))]
        result = await self.archive.ready()
        self.assertEqual(result.id, 70)
        self.guild.create_text_channel.assert_not_awaited()
        self.assertEqual(self.store.get(DESTINATION_KEY)['channel'], 70)

    async def test_new_destination_has_exact_private_overwrites_and_tracked_creation(self):
        self.store.put(DESTINATION_KEY, {})
        voice = MagicMock(spec=discord.VoiceChannel)
        voice.category_id, voice.position = 80, 22
        self.guild.fetch_channels.return_value.append(voice)
        self.guild.create_text_channel = AsyncMock(return_value=self.destination)
        result = await self.archive.ready()
        self.assertEqual(result.id, 70)
        kwargs = self.guild.create_text_channel.await_args.kwargs
        self.assertEqual(kwargs['position'], 22)
        self.assertIs(kwargs['category'], self.category)
        self.assertIs(kwargs['overwrites'][self.guild.default_role].view_channel, False)
        self.assertIs(kwargs['overwrites'][self.roles[13]].send_messages, False)
        self.assertIs(kwargs['overwrites'][self.roles[13]].view_channel, True)
        self.assertEqual(kwargs['reason'], 'VIce ticket archive ' + self.store.get(DESTINATION_KEY)['nonce'])
        self.assertTrue(self.states)
        await self.archive.ready()
        self.guild.create_text_channel.assert_awaited_once()

    async def test_owner_overwrite_works_with_disabled_member_cache(self):
        self.store.put(DESTINATION_KEY, {})
        self.guild.get_member.side_effect = lambda member_id: None
        self.guild.get_member.reset_mock()
        self.guild.create_text_channel = AsyncMock(return_value=self.destination)
        await self.archive.ready()
        overwrites = self.guild.create_text_channel.await_args.kwargs['overwrites']
        owner = next(target for target in overwrites if target.id == OWNER_ID)
        self.assertIsInstance(owner, discord.Object)
        self.assertIs(owner.type, discord.Member)
        self.assertIs(overwrites[owner].view_channel, True)
        self.guild.get_member.assert_not_called()

    async def test_registered_legacy_archive_gets_publish_denies_once_without_access_changes(self):
        before = {target.id: (overwrite.view_channel, overwrite.read_message_history)
                  for target, overwrite in self.destination.overwrites.items()}
        for target, overwrite in self.destination.overwrites.items():
            if target.id != BOT_ID:
                overwrite.update(**{flag: None for flag in LEGACY_WRITE_GAPS})
        async def edit(**kwargs):
            self.destination.overwrites = kwargs['overwrites']
            return self.destination
        self.destination.edit = AsyncMock(side_effect=edit)
        await self.archive.ready()
        for target, overwrite in self.destination.overwrites.items():
            self.assertEqual((overwrite.view_channel, overwrite.read_message_history), before[target.id])
            if target.id != BOT_ID:
                self.assertIs(overwrite.use_application_commands, False)
                self.assertIs(overwrite.use_external_apps, False)
        self.assertEqual(self.store.get(DESTINATION_KEY)['publication_version'], PUBLICATION_VERSION)
        self.assertEqual(self.system.track.await_args.args[0], 'TICKET_ARCHIVE_READONLY')
        await self.archive.ready()
        self.destination.edit.assert_awaited_once()

    async def test_legacy_migration_refuses_visibility_drift_and_unexpected_publication_allow(self):
        self.destination.edit = AsyncMock()
        self.destination.overwrites[self.guild.default_role].view_channel = True
        with self.assertRaises(ValueError):
            await self.archive.ready()
        self.destination.overwrites = self.archive.overwrites(self.guild)
        self.destination.overwrites[self.guild.default_role].use_external_apps = True
        with self.assertRaises(ValueError):
            await self.archive.ready()
        self.destination.edit.assert_not_awaited()
        self.assertNotIn('publication_version', self.store.get(DESTINATION_KEY))

    async def test_preparation_failure_never_records_a_dispatched_attempt(self):
        self.store.put(DESTINATION_KEY, {})
        self.roles.pop(13)
        self.guild.create_text_channel = AsyncMock(return_value=self.destination)
        with self.assertRaisesRegex(ValueError, 'Faltan roles'):
            await self.archive.ready()
        self.assertNotIn('attempted_at', self.store.get(DESTINATION_KEY))
        self.guild.create_text_channel.assert_not_awaited()

    async def test_exact_logged_pre_dispatch_failure_is_recovered_once_with_before_state(self):
        original = dict(guild=GUILD_ID, nonce='confirmed-owner-cache-failure',
            started_at='2026-11-18T18:04:52.900000+00:00', attempted_at='2026-11-18T18:04:53.100000+00:00')
        self.store.put(DESTINATION_KEY, original)
        self.guild.fetch_channels.return_value = [self.category, self.channel]
        self.guild.create_text_channel = AsyncMock(return_value=self.destination)
        await self.archive.ready()
        record = self.store.get(DESTINATION_KEY)
        self.assertEqual(record['recovered_pre_dispatch_bug_v1']['original'], original)
        self.assertEqual(record['channel'], 70)
        self.assertEqual(self.states[0]['destination'], original)
        self.assertEqual(self.system.track.await_args_list[0].args[0], 'TICKET_ARCHIVE_RECOVERY')
        await self.archive.ready()
        self.guild.create_text_channel.assert_awaited_once()

    async def test_pre_dispatch_exception_never_retries_unknown_or_ambiguous_attempts(self):
        self.guild.create_text_channel = AsyncMock(return_value=self.destination)
        records = [
            dict(guild=GUILD_ID, nonce='outside-window', started_at='2026-11-18T18:04:53+00:00',
                 attempted_at='2026-11-18T18:04:55+00:00'),
            dict(guild=GUILD_ID, nonce='possible-channel', started_at='2026-11-18T18:04:53+00:00',
                 attempted_at='2026-11-18T18:04:53+00:00'),
            dict(guild=GUILD_ID, nonce='already-recovered', started_at='2026-11-18T18:04:53+00:00',
                 attempted_at='2026-11-18T18:04:53+00:00', recovered_pre_dispatch_bug_v1={}),
        ]
        for record in records:
            with self.subTest(nonce=record['nonce']):
                self.store.put(DESTINATION_KEY, record)
                with self.assertRaises(ValueError):
                    await self.archive.ready()
                self.assertEqual(self.store.get(DESTINATION_KEY), record)
        self.guild.create_text_channel.assert_not_awaited()

    async def test_streamed_download_rejects_truncated_data(self):
        original = TicketArchive.download.__get__(self.archive)
        response = NS(status=200, content=NS(iter_chunked=lambda size: values([b'ab', b'c'])))
        response_context = MagicMock()
        response_context.__aenter__ = AsyncMock(return_value=response)
        response_context.__aexit__ = AsyncMock(return_value=False)
        session = NS(get=Mock(return_value=response_context))
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=False)
        with patch('vice_ticket_archive.aiohttp.ClientSession', return_value=session_context):
            with self.assertRaisesRegex(ValueError, 'incompleta'):
                await original('https://cdn.discordapp.com/attachments/55/file.txt',
                               self.archive.root / 'short', 5, 10)
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])

    async def test_download_rejects_external_or_unsafe_urls_without_network(self):
        original = TicketArchive.download.__get__(self.archive)
        for url in ('http://cdn.discordapp.com/attachments/1/x',
                    'https://example.com/file', 'https://cdn.discordapp.com.evil.test/attachments/x',
                    'https://cdn.discordapp.com/not-attachments/file'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                await original(url, self.archive.root / 'unsafe', 5, 10)


if __name__ == '__main__':
    unittest.main()
