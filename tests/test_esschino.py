import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from change_log import ChangeLog
from esschino import (EssChino, StudioStore, PROTECTED_CHANNEL, ORIGINAL_GUILD, OWNER_ACCOUNTS,
    REQUEST, ENV, ROLE_SPECS, CHANNELS, EntryView, NotificationsView, SupportView, AdminView,
    TicketView, TicketModal, ShopModal, PurchaseModal, deletion_plan, validate_target, valid_shop_url)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'store.db'
        self.store = StudioStore(self.path)
        self.store.initialize()

    def test_frozen_inventory_survives_restart_and_preserves_other_bot_data(self):
        with self.store.db() as db, db:
            db.execute('CREATE TABLE original_bot(value TEXT)')
            db.execute("INSERT INTO original_bot VALUES ('conservar')")
        self.store.put('original_channels', [10, 11])
        self.store.add_ticket(40, 99, 'compras')
        other = StudioStore(self.path)
        other.initialize()
        self.assertEqual(other.get('original_channels'), [10, 11])
        self.assertEqual(other.ticket(40)['owner'], '99')
        with other.db() as db:
            self.assertEqual(db.execute('SELECT value FROM original_bot').fetchone()[0], 'conservar')

    def test_purchase_reference_cannot_grant_two_members_a_purchase(self):
        self.store.purchase('TBX-123', 10, 50)
        self.store.purchase('tbx-123', 10, 50)
        with self.assertRaises(ValueError):
            self.store.purchase('TBX-123', 11, 50)

    def test_messages_and_verified_attachment_blobs_survive_restart(self):
        payload = dict(content='pedido privado', attachments=[dict(id='5')])
        self.store.save_message('ticket', 30, 100, payload)
        self.store.save_file(5, 'prueba.txt', b'evidencia')
        fresh = StudioStore(self.path)
        self.assertEqual(fresh.transcript(30), [payload])
        with fresh.db() as db:
            self.assertEqual(db.execute('SELECT data FROM esschino_files').fetchone()[0], b'evidencia')


class ScopeTests(unittest.TestCase):
    def target(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = PROTECTED_CHANNEL
        channel.guild = NS(id=222, name='Servidor de EssChino', owner_id=min(OWNER_ACCOUNTS),
            me=NS(guild_permissions=discord.Permissions(administrator=True)))
        return channel

    def test_only_exact_channel_in_verified_separate_guild_is_accepted(self):
        channel = self.target()
        self.assertIs(validate_target(channel), channel.guild)
        for field, value in [('id', ORIGINAL_GUILD), ('owner_id', 55), ('name', 'Otra comunidad')]:
            channel = self.target()
            setattr(channel.guild, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_target(channel)
        channel = self.target()
        with self.assertRaises(ValueError):
            validate_target(channel, saved_guild=999)
        channel.id = 1
        with self.assertRaises(ValueError):
            validate_target(channel)

    def test_missing_bot_administrator_blocks_installation(self):
        channel = self.target()
        channel.guild.me.guild_permissions = discord.Permissions(manage_channels=True)
        with self.assertRaises(ValueError):
            validate_target(channel)

    def test_deletion_never_expands_to_new_or_protected_channels(self):
        guild = NS(id=222)
        old = NS(id=10, guild=guild)
        new = NS(id=20, guild=guild)
        protected = NS(id=PROTECTED_CHANNEL, guild=guild)
        self.assertEqual(deletion_plan([old, new, protected], [10], 222), [old])
        with self.assertRaises(ValueError):
            deletion_plan([protected], [PROTECTED_CHANNEL], 222)
        with self.assertRaises(ValueError):
            deletion_plan([old], [10], ORIGINAL_GUILD)
        with self.assertRaises(ValueError):
            deletion_plan([NS(id=10, guild=NS(id=999))], [10], 222)

    def test_shop_url_rejects_non_https_and_embedded_credentials(self):
        self.assertEqual(valid_shop_url('https://example.tebex.io/'), 'https://example.tebex.io/')
        for value in ('http://example.tebex.io', 'javascript:alert(1)', 'https://secret@example.com', 'https://a b.com'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                valid_shop_url(value)


class InstallationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'store.db'
        self.bot = MagicMock()
        self.bot.user.id = 500
        self.system = EssChino(self.bot, self.path)
        await self.system.start()

    async def test_request_gate_is_required_before_resolving_or_mutating_discord(self):
        self.bot.fetch_channel = AsyncMock()
        with patch.dict('os.environ', {ENV: ''}):
            await self.system.ready()
        self.bot.fetch_channel.assert_not_awaited()

    async def test_setup_is_durable_scoped_and_not_repeated_after_restart(self):
        channel = ScopeTests().target()
        guild = channel.guild
        guild.fetch_roles = AsyncMock(return_value=[])
        guild.fetch_channels = AsyncMock(return_value=[channel, NS(id=10)])
        guild.channels = [channel, NS(id=10)]
        self.bot.fetch_channel = AsyncMock(return_value=channel)
        self.bot.get_guild.return_value = guild
        self.bot.changes = ChangeLog(self.bot, self.path, ORIGINAL_GUILD)
        self.bot.changes.journal.initialize()
        self.system.snapshot = AsyncMock(return_value={'guild_id': guild.id, 'before': 'private copy'})

        async def apply(*args):
            row = self.bot.changes.journal.by_key(f'operation:{ENV}:{REQUEST}')
            self.assertEqual(row['status'], 'iniciado')
            self.assertEqual(json.loads(row['before_json'])['guild_id'], guild.id)
            self.assertEqual(self.system.store.get('original_channels'), [10])
            self.system.store.put('setup_complete', 123)
        self.system.install = AsyncMock(side_effect=apply)
        with patch.dict('os.environ', {ENV: REQUEST}):
            await self.system.ready()
        self.system.install.assert_awaited_once()
        # A newly added channel cannot become an original on a later startup.
        guild.fetch_channels.return_value.append(NS(id=20))
        restarted = EssChino(self.bot, self.path)
        await restarted.start()
        restarted.install = AsyncMock()
        restarted.verify = AsyncMock()
        with patch.dict('os.environ', {ENV: REQUEST}):
            await restarted.ready()
        restarted.install.assert_not_awaited()
        restarted.verify.assert_awaited_once()
        self.assertEqual(restarted.store.get('original_channels'), [10])

    async def test_archive_failure_stops_deletion_and_role_creation(self):
        protected = ScopeTests().target()
        guild = protected.guild
        guild.default_role = MagicMock()
        guild.get_role = MagicMock(return_value=None)
        owner = MagicMock()
        guild.fetch_member = AsyncMock(return_value=owner)
        old = MagicMock()
        old.id = 10
        guild.fetch_channels = AsyncMock(return_value=[old, protected])
        guild.create_role = AsyncMock()
        protected.edit = AsyncMock()
        protected.permissions_for.return_value.view_channel = False
        self.bot.fetch_channel = AsyncMock(return_value=protected)
        self.system.archive_originals = AsyncMock(side_effect=ValueError('copy failed'))
        # Hashable members for the overwrite dictionary.
        guild.me = MagicMock()
        with self.assertRaisesRegex(ValueError, 'copy failed'):
            await self.system.install(guild, protected, [10])
        protected.edit.assert_awaited_once()
        old.delete.assert_not_called()
        guild.create_role.assert_not_awaited()

    async def test_private_and_read_only_policies_have_expected_explicit_overwrites(self):
        guild = MagicMock()
        guild.default_role.id = 222
        guild.me.id = 500
        guild.get_role.return_value = None
        owner = MagicMock()
        owner.id = 700
        for index, (key, *_) in enumerate(ROLE_SPECS, 100):
            role = MagicMock(spec=discord.Role)
            role.id = index
            self.system.store.put('role:' + key, index)
            self.system.roles[index] = role
        private = self.system.overwrites(guild, 'owner', owner)
        self.assertFalse(private[guild.default_role].view_channel)
        self.assertEqual(set(private), {guild.default_role, guild.me, owner})
        public = self.system.overwrites(guild, 'read', owner)
        self.assertTrue(public[guild.default_role].view_channel)
        self.assertFalse(public[guild.default_role].send_messages)
        customer = self.system.overwrites(guild, 'customer', owner)
        self.assertFalse(customer[guild.default_role].view_channel)
        self.assertTrue(customer[self.system.role(guild, 'customer')].view_channel)
        reviews = self.system.overwrites(guild, 'review', owner)
        self.assertFalse(reviews[guild.default_role].send_messages)
        self.assertTrue(reviews[self.system.role(guild, 'customer')].send_messages)

    async def test_all_persistent_panels_and_modals_are_valid_for_discord(self):
        for cls in (EntryView, NotificationsView, SupportView, AdminView, TicketView):
            self.assertTrue(cls(self.system).is_persistent())
        for modal in (TicketModal(self.system, 'compras'), ShopModal(self.system), PurchaseModal(self.system)):
            self.assertLessEqual(len(modal.to_dict()['components']), 5)
        for key, *rest in CHANNELS:
            if not rest[-1]:
                title, body = self.system.panel(key)
                embed = self.system.embed(title, body)
                self.assertLessEqual(len(title), 256)
                self.assertLessEqual(len(body), 4096)
                self.assertLess(len(embed), 6000)

    async def test_old_guild_messages_do_not_access_store_or_archive(self):
        self.system.store = MagicMock()
        await self.system.observe(NS(guild=NS(id=ORIGINAL_GUILD)))
        self.system.store.get.assert_not_called()
