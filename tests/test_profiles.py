from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from player_cards import PlayerCard, profile_embed, profile_export


def member():
    return SimpleNamespace(id=123, name='jugador', display_name='Jugador RP', display_avatar=SimpleNamespace(url='https://cdn.discordapp.com/embed/avatars/0.png'))


def data(page=1, pages=2):
    events = [dict(id=page, title=f'Evento {page}', location='Ciudad', starts_at='2030-01-01T00:00:00+00:00', status='finished', winner1='123', winner2='456', winner3='789', prizes='Premios', description='Texto')]
    return dict(stats=dict(participations=6, first=2, second=1, third=0), rank=12, ranked_players=25, total_events=6, page=page, pages=pages, events=events)


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = Mock()
        async def call(method, key, *args):
            return data(args[0]) if method == 'profile' else data()['events']
        self.bot.event_features.call = AsyncMock(side_effect=call)
        self.access = AsyncMock()
        self.card = PlayerCard(self.bot, 42, member(), self.access)
        self.interaction = Mock()
        self.interaction.user.id = 42
        self.interaction.guild.get_member.return_value = None
        self.interaction.response.defer = AsyncMock()
        self.interaction.response.send_message = AsyncMock()
        self.interaction.edit_original_response = AsyncMock()
        self.interaction.followup.send = AsyncMock()

    async def test_card_avatar_username_stats_and_pagination_edit_same_message(self):
        embed = await self.card.render()
        self.assertEqual(embed.thumbnail.url, member().display_avatar.url)
        self.assertIn('jugador', embed.description)
        self.assertIn('#12', embed.fields[2].value)
        self.assertTrue(self.card.previous.disabled)
        self.assertFalse(self.card.next.disabled)
        await self.card.change(self.interaction, 1)
        self.interaction.edit_original_response.assert_awaited_once()
        self.interaction.followup.send.assert_not_awaited()
        self.access.assert_awaited_once_with(self.interaction)
        self.assertFalse(self.card.previous.disabled)
        self.assertTrue(self.card.next.disabled)

    async def test_card_owner_controls_and_export_is_private(self):
        self.interaction.user.id = 99
        self.assertFalse(await self.card.interaction_check(self.interaction))
        self.assertTrue(self.interaction.response.send_message.call_args.kwargs['ephemeral'])
        self.interaction.user.id = 42
        self.assertTrue(await self.card.interaction_check(self.interaction))
        await self.card.export.callback(self.interaction)
        self.assertTrue(self.interaction.followup.send.call_args.kwargs['ephemeral'])
        file = self.interaction.followup.send.call_args.kwargs['file']
        self.assertIn('Evento 1', file.fp.read().decode())
        self.assertEqual(self.interaction.followup.send.call_args.kwargs['allowed_mentions'].to_dict()['parse'], [])

    async def test_card_timeout_disables_controls(self):
        self.card.message = Mock()
        self.card.message.edit = AsyncMock()
        await self.card.on_timeout()
        self.assertTrue(all(item.disabled for item in self.card.children))
        self.card.message.edit.assert_awaited_once()

    async def test_large_card_stays_within_embed_limits_and_exports_details(self):
        record = data()
        record['events'] = []
        for key in range(5):
            event = data()['events'][0].copy()
            event.update(id=key, title='*' * 90, location='*' * 200, description='Descripción completa')
            record['events'].append(event)
        embed = profile_embed(member(), record)
        self.assertLessEqual(len(embed), 6000)
        self.assertTrue(all(len(field.name) <= 256 and len(field.value) <= 1024 for field in embed.fields))
        exported = profile_export(member(), record['events'])
        self.assertIn('Descripción completa', exported)
        self.assertIn('Primer lugar', exported)
