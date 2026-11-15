import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from esschino import EssChino, CATEGORIES, CHANNELS
from store_community import CommunityStore, StoreCommunity, IdeasPanel, ReviewsPanel, IdeaVotes, IdeaModal, ReviewModal
from store_bot import StoreBot, GUILD_ID


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CommunityStore(Path(self.tmp.name) / 'store.db')
        self.store.initialize()

    def test_one_vote_per_member_changes_direction_and_toggles_off(self):
        row = self.store.new_idea(10, 'Una mejora', 'Mejorar el instalador')
        self.store.vote(row, 20, 1)
        self.store.vote(row, 20, -1)
        self.assertEqual(self.store.counts(row), {-1: 1})
        self.store.vote(row, 20, -1)
        self.assertEqual(self.store.counts(row), {})
        self.store.vote(row, 21, 1)
        self.store.decide(row, 'completada', 'Publicada')
        with self.assertRaises(ValueError):
            self.store.vote(row, 22, 1)

    def test_reviews_update_same_customer_product_without_creating_duplicates(self):
        first = self.store.review(10, 'Script A', 5, 'Mi experiencia')
        second = self.store.review(10, 'script a', 4, 'Comentario actualizado')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(second['rating'], 4)
        self.assertEqual(len(self.store.snapshot()['studio_reviews']), 1)

    def test_unverified_member_cannot_review_even_if_administrator(self):
        system = MagicMock()
        system.store.get.side_effect = lambda key: 222 if key == 'guild' else 99
        community = StoreCommunity(system, self.store.path)
        member = MagicMock(spec=discord.Member)
        member.bot = False
        member.roles = []
        member.guild_permissions = discord.Permissions(administrator=True)
        interaction = NS(guild_id=222, user=member)
        with self.assertRaises(ValueError):
            community.customer(interaction)
        member.roles = [NS(id=99)]
        community.customer(interaction)
        interaction.guild_id = 333
        with self.assertRaises(ValueError):
            community.customer(interaction)


class LayoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.system = EssChino(MagicMock(), Path(self.tmp.name) / 'store.db')
        await self.system.start()

    async def test_exact_requested_static_categories_and_channels(self):
        self.assertEqual([name for _,name,_ in CATEGORIES],
            ['📌 INFORMACIÓN','🛒 TIENDA','🛠️ SOPORTE','💬 COMUNIDAD','🔒 EQUIPO'])
        expected = ['👋・bienvenida','📜・normas','📢・anuncios','🧭・cómo-comprar',
            '🛍️・tienda-tebex','📦・catálogo-scripts','🎬・demostraciones','🏷️・ofertas','🔄・actualizaciones',
            '🎫・abrir-ticket','📚・guías-instalación','❓・preguntas-frecuentes',
            '💬・general','💡・sugerencias','⭐・reseñas','👥・chat-staff','📋・gestión-soporte','📑・registros']
        self.assertEqual([row[2] for row in CHANNELS], expected)
        self.assertNotIn('tickets', [row[0] for row in CATEGORIES])
        self.assertNotIn('closed', [row[0] for row in CATEGORIES])

    async def test_open_ticket_category_is_created_above_every_other_category(self):
        category = NS(edit=AsyncMock())
        self.system.ensure_channel = AsyncMock(return_value=category)
        self.system.overwrites = MagicMock(return_value={})
        await self.system.ticket_category(MagicMock(), False, MagicMock())
        self.assertEqual(self.system.ensure_channel.await_args.args[2], 'Tickets Abiertos')
        self.assertEqual(category.edit.await_args.kwargs['position'], 0)

    async def test_closing_creates_separate_archive_and_keeps_open_tickets_at_the_top(self):
        closed = NS(edit=AsyncMock())
        opened = NS(edit=AsyncMock())
        self.system.ensure_channel = AsyncMock(return_value=closed)
        self.system.overwrites = MagicMock(return_value={})
        self.system.channel = MagicMock(return_value=opened)
        await self.system.ticket_category(MagicMock(), True, MagicMock())
        self.assertEqual(self.system.ensure_channel.await_args.args[2], 'Tickets Cerrados')
        self.assertEqual(closed.edit.await_args.kwargs['position'], 1)
        self.assertEqual(opened.edit.await_args.kwargs['position'], 0)

    async def test_community_controls_are_persistent_and_forms_fit_discord_limits(self):
        community = StoreCommunity(self.system, self.system.store.path)
        self.system.community = community
        await community.start()
        for cls in (IdeasPanel, ReviewsPanel, IdeaVotes):
            self.assertTrue(cls(self.system).is_persistent())
        for modal in (IdeaModal(community), ReviewModal(community)):
            self.assertLessEqual(len(modal.to_dict()['components']), 5)

    async def test_active_bot_only_registers_store_workflows_in_the_correct_guild(self):
        bot = StoreBot()
        roots = {command.name for command in bot.tree.get_commands(guild=discord.Object(id=GUILD_ID))}
        self.assertEqual(roots, {'ayuda','tienda','soporte','mis-tickets','sugerir','resena','studio'})
        self.assertFalse(bot.tree.get_commands())
        self.assertFalse(bot.tree.get_commands(guild=discord.Object(id=1244988345327550565)))
        with self.assertRaises(ValueError):
            bot.authorize(NS(guild_id=1244988345327550565))
