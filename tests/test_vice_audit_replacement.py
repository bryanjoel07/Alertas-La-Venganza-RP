"""Frozen-record replacement, exact bot ownership and restart-safe cleanup."""
from copy import deepcopy
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

import discord

from tests import test_vice_audit as runtime_fixture
from vice_audit import AUDIT_VERSION, ViceAudit, embed_marker, marker, stamp_embed
from vice_design import BOT_ID, GUILD_ID, OWNER_ID


class AuditReplacementTests(unittest.IsolatedAsyncioTestCase):
    # Share the runtime fixture without inheriting and duplicating its test cases.
    embed = runtime_fixture.AuditRuntimeTests.embed
    queue = runtime_fixture.AuditRuntimeTests.queue

    async def asyncSetUp(self):
        self.deleted = []
        await runtime_fixture.AuditRuntimeTests.asyncSetUp(self)
        self.audit.scan = AsyncMock(return_value=0)
        self.audit.install_panel = AsyncMock()
        async def fetch(message_id):
            found = next((m for m in self.messages if m.id == message_id), None)
            if found is None:
                raise discord.NotFound(NS(status=404, reason='Not Found'),
                    {'code': 10008, 'message': 'Unknown Message'})
            return found
        self.channel.fetch_message = AsyncMock(side_effect=fetch)

    def message(self, message_id, embeds, author=BOT_ID):
        msg = runtime_fixture.AuditRuntimeTests.message(self, message_id, embeds, author)
        msg.channel, msg.content = self.channel, ''
        msg.attachments, msg.components, msg.pinned = [], [], False
        async def delete():
            # A full journal snapshot must already exist when deletion starts.
            self.deleted.append((msg.id, deepcopy(self.snapshots)))
            self.messages.remove(msg)
        msg.delete = AsyncMock(side_effect=delete)
        return msg

    def seed_batch(self, keys, message_id=9001, *, published=True):
        embeds = []
        for key in keys:
            e = self.embed(size=1300)
            e.set_footer(text=e.footer.text + ' • ' + marker(key))
            self.audit.store.enqueue(key, e.to_dict(), 'audit', self.when.isoformat(), historical=True)
            embeds.append(e)
        rows = self.audit.store.reserve(keys, 'legacy-batch-' + str(message_id), self.when.isoformat())
        if published:
            self.audit.store.mark_sent([(row['key'], row['fingerprint']) for row in rows], str(message_id))
        msg = self.message(message_id, embeds)
        self.messages.append(msg)
        return msg

    def seed_panel(self, message_id=9901, *, author=BOT_ID, footer='VIce District • panel:log'):
        self.values['panel:log'] = message_id
        embed = discord.Embed(title='Panel anterior', description='Panel largo anterior').set_footer(text=footer)
        msg = self.message(message_id, [embed], author=author)
        self.messages.append(msg)
        return msg

    async def test_marker_is_url_metadata_with_legacy_footer_recovery(self):
        original = self.embed()
        stamped = stamp_embed(original, 'audit:one', self.channel.id)
        self.assertEqual(embed_marker(stamped), marker('audit:one'))
        self.assertEqual(stamped.footer.text, original.footer.text)
        self.assertNotIn('ref:', stamped.footer.text)
        self.assertIn(f'/channels/{GUILD_ID}/{self.channel.id}', stamped.url)
        self.assertEqual(original.url, None)
        legacy = self.embed().set_footer(text='VIce District • ' + marker('audit:legacy'))
        self.assertEqual(embed_marker(legacy), marker('audit:legacy'))
        untrusted = self.embed()
        untrusted.url = 'https://example.com/?ref=' + marker('audit:one')[4:]
        self.assertIsNone(embed_marker(untrusted))
        wrong_guild = self.embed()
        wrong_guild.url = f'https://discord.com/channels/123/{self.channel.id}?ref=' + marker('audit:one')[4:]
        self.assertIsNone(embed_marker(wrong_guild))

    async def test_replacement_deletes_only_frozen_bot_message_and_preserves_full_old_data(self):
        old = self.seed_batch(['audit:a', 'audit:b'])
        originals = [deepcopy(self.audit.store.get(key)) for key in ('audit:a', 'audit:b')]
        unrelated = self.message(9002, [self.embed()], author=OWNER_ID)
        another_bot_card = self.message(9003, [self.embed()])
        self.messages.extend([unrelated, another_bot_card])
        await self.audit.replace_long_records()
        manifest = self.audit.store.replacement(AUDIT_VERSION)
        self.assertEqual(manifest['stage'], 'queue_ready')
        self.assertEqual(manifest['originals'], originals)
        self.assertEqual(manifest['message_ids'], ['9001'])
        self.assertEqual(manifest['deleted_message_ids'], ['9001'])
        self.assertEqual(manifest['reset_count'], 2)
        old.delete.assert_awaited_once()
        unrelated.delete.assert_not_awaited()
        another_bot_card.delete.assert_not_awaited()
        self.assertEqual({m.id for m in self.messages}, {9002, 9003})
        self.audit.scan.assert_awaited_once_with(full=True)
        self.audit.install_panel.assert_awaited_once()
        snapshot = next(s for s in self.deleted[0][1] if s.get('message') == old.id)
        self.assertEqual(snapshot['author'], BOT_ID)
        self.assertEqual(snapshot['channel'], self.channel.id)
        self.assertEqual(snapshot['keys'], ['audit:a', 'audit:b'])
        self.assertIn('D' * 1300, json.dumps(snapshot))
        for key in ('audit:a', 'audit:b'):
            row = self.audit.store.get(key)
            self.assertIsNone(row['message_id'])
            self.assertIsNone(row['batch_key'])
            self.assertIsNone(row['sent_fingerprint'])
            self.assertEqual(row['event_time'], self.when.isoformat())
            compact = discord.Embed.from_dict(json.loads(row['payload_json']))
            self.assertLessEqual(len(compact), 800)
            self.assertEqual(embed_marker(compact), marker(key))
            self.assertNotIn('ref:', compact.footer.text or '')

    async def test_freeze_precedes_scan_and_new_message_during_scan_is_not_deleted(self):
        old = self.seed_batch(['audit:old'])
        added = []
        async def scan(*, full):
            self.assertTrue(full)
            frozen = self.audit.store.replacement(AUDIT_VERSION)
            self.assertEqual([r['key'] for r in frozen['originals']], ['audit:old'])
            added.append(self.seed_batch(['audit:new'], message_id=9004))
            return 1
        self.audit.scan.side_effect = scan
        await self.audit.replace_long_records()
        old.delete.assert_awaited_once()
        added[0].delete.assert_not_awaited()
        self.assertEqual(self.audit.store.get('audit:new')['message_id'], '9004')
        self.assertEqual(self.audit.store.replacement(AUDIT_VERSION)['message_ids'], ['9001'])

    async def test_foreign_author_at_frozen_id_fails_closed(self):
        old = self.seed_batch(['audit:one'])
        old.author.id = OWNER_ID
        with self.assertRaises(ValueError):
            await self.audit.replace_long_records()
        old.delete.assert_not_awaited()
        self.system.track.assert_not_awaited()
        self.assertEqual(self.audit.store.replacement(AUDIT_VERSION)['stage'], 'prepared')
        self.assertEqual(self.audit.store.get('audit:one')['message_id'], '9001')

    async def test_extra_or_mixed_markers_and_message_content_fail_closed(self):
        old = self.seed_batch(['audit:one'])
        original = deepcopy(old.embeds)
        cases = (
            [original[0], stamp_embed(self.embed(), 'audit:other', self.channel.id)],
            [stamp_embed(self.embed(), 'audit:other', self.channel.id)],
            [original[0], original[0]],
        )
        for embeds in cases:
            old.embeds = embeds
            with self.subTest(count=len(embeds)), self.assertRaises(ValueError):
                await self.audit.replace_long_records()
        old.embeds = original
        old.content = 'This is extra content outside the frozen card.'
        with self.assertRaises(ValueError):
            await self.audit.replace_long_records()
        old.content = ''
        for attribute in ('attachments', 'components'):
            setattr(old, attribute, [NS(id=1)])
            with self.subTest(extra=attribute), self.assertRaises(ValueError):
                await self.audit.replace_long_records()
            setattr(old, attribute, [])
        old.delete.assert_not_awaited()
        self.system.track.assert_not_awaited()
        self.assertEqual(self.audit.store.replacement(AUDIT_VERSION)['stage'], 'prepared')

    async def test_reserved_send_crash_recovers_only_complete_bot_batch(self):
        old = self.seed_batch(['audit:a', 'audit:b'], published=False)
        partial = self.message(9002, old.embeds[:1])
        foreign = self.message(9003, old.embeds, author=OWNER_ID)
        mixed = self.message(9004, old.embeds + [stamp_embed(self.embed(), 'audit:x', self.channel.id)])
        self.messages[:] = [partial, foreign, mixed, old]
        await self.audit.replace_long_records()
        old.delete.assert_awaited_once()
        for msg in (partial, foreign, mixed):
            msg.delete.assert_not_awaited()
        manifest = self.audit.store.replacement(AUDIT_VERSION)
        self.assertEqual(manifest['recovered_messages'], {'9001': ['audit:a', 'audit:b']})
        self.assertEqual(manifest['deleted_message_ids'], ['9001'])
        self.assertTrue(all(row['message_id'] is None for row in manifest['originals']))
        self.assertIsNone(self.channel.history.call_args.kwargs['limit'])

    async def test_delete_then_ack_crash_resumes_from_404_without_second_delete(self):
        old = self.seed_batch(['audit:one'])
        real_db = self.audit.db
        async def interrupt(method, *args, **kwargs):
            if method == 'mark_replacement_deleted':
                raise OSError('crashed after Discord accepted delete')
            return await real_db(method, *args, **kwargs)
        with patch.object(self.audit, 'db', side_effect=interrupt):
            with self.assertRaises(OSError):
                await self.audit.replace_long_records()
        self.assertEqual(self.audit.store.replacement(AUDIT_VERSION)['deleted_message_ids'], [])
        self.assertEqual(self.messages, [])
        restarted = ViceAudit(self.system)
        await restarted.start()
        self.addAsyncCleanup(restarted.close)
        restarted.scan, restarted.install_panel = AsyncMock(return_value=0), AsyncMock()
        await restarted.replace_long_records()
        old.delete.assert_awaited_once()
        self.assertEqual(restarted.store.replacement(AUDIT_VERSION)['stage'], 'queue_ready')
        self.assertEqual(restarted.store.replacement(AUDIT_VERSION)['deleted_message_ids'], ['9001'])
        self.assertEqual(restarted.store.stats()['pending'], 1)

    async def test_exact_stored_panel_is_replaced_and_unrelated_panel_is_preserved(self):
        panel = self.seed_panel()
        other = self.message(9902, panel.embeds)
        self.messages.append(other)
        await self.audit.replace_long_records()
        panel.delete.assert_awaited_once()
        other.delete.assert_not_awaited()
        state = self.audit.store.state('replacement_panel:' + AUDIT_VERSION)
        self.assertEqual(state, {'message_id': 9901, 'deleted': True})
        self.assertTrue(any(s.get('message') == 9901 and s.get('keys') == ['panel:log']
                            for s in self.snapshots))
        self.audit.install_panel.assert_awaited_once()

    async def test_panel_author_or_footer_mismatch_aborts_without_deleting(self):
        panel = self.seed_panel(author=OWNER_ID)
        with self.assertRaises(ValueError):
            await self.audit.replace_long_records()
        panel.author.id = BOT_ID
        panel.embeds[0].set_footer(text='VIce District • panel:welcome')
        with self.assertRaises(ValueError):
            await self.audit.replace_long_records()
        panel.delete.assert_not_awaited()
        self.audit.install_panel.assert_not_awaited()
        self.assertFalse(self.audit.store.state('replacement_panel:' + AUDIT_VERSION)['deleted'])

    async def test_missing_panel_is_acknowledged_without_touching_another_message(self):
        self.values['panel:log'] = 9901
        other = self.message(9902, [self.embed()])
        self.messages.append(other)
        await self.audit.replace_long_records()
        other.delete.assert_not_awaited()
        self.assertTrue(self.audit.store.state('replacement_panel:' + AUDIT_VERSION)['deleted'])
        self.assertEqual(self.audit.store.replacement(AUDIT_VERSION)['stage'], 'queue_ready')

    async def test_queue_ready_and_complete_do_not_delete_or_reset_a_second_time(self):
        old = self.seed_batch(['audit:one'])
        await self.audit.replace_long_records()
        reset = self.audit.store.replacement(AUDIT_VERSION)['reset_at']
        before = deepcopy(self.audit.store.get('audit:one'))
        self.audit.scan.reset_mock()
        self.audit.install_panel.reset_mock()
        self.channel.fetch_message.reset_mock()
        await self.audit.replace_long_records()
        self.assertEqual(self.audit.store.get('audit:one'), before)
        self.audit.scan.assert_not_awaited()
        self.audit.install_panel.assert_not_awaited()
        self.channel.fetch_message.assert_not_awaited()
        await self.audit.flush_once()
        replacement_row = deepcopy(self.audit.store.get('audit:one'))
        self.audit.store.set_replacement_stage(AUDIT_VERSION, 'complete')
        await self.audit.replace_long_records()
        self.assertEqual(self.audit.store.get('audit:one'), replacement_row)
        self.assertEqual(self.audit.store.replacement(AUDIT_VERSION)['reset_at'], reset)
        old.delete.assert_awaited_once()
        self.assertEqual(self.audit.store.stats()['pending'], 0)


if __name__ == '__main__':
    unittest.main()
