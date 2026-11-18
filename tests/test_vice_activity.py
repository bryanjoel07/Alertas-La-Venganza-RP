"""Truthful, bounded and guild-isolated gateway activity records."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from vice_activity import AMBER, GREEN, RED, ViceActivity
from vice_design import GUILD_ID, OWNER_ID


class ActivityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = NS(id=GUILD_ID, owner_id=OWNER_ID)
        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')
            return guild
        self.audit = NS(system=NS(validate_guild=Mock(side_effect=validate)), publish=AsyncMock())
        self.activity = ViceActivity(self.audit)
        self.member = NS(id=333, name='jugador', display_name='El Corillo', guild=self.guild,
            created_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
            display_avatar=NS(url='https://cdn.discordapp.com/avatars/333/hash.png'))
        self.lobby = NS(id=100, name='Lobby', guild=self.guild)
        self.crew = NS(id=101, name='Crew 01', guild=self.guild)

    def state(self, channel, **kwargs):
        values = dict(channel=channel, self_mute=False, self_deaf=False, mute=False,
                      deaf=False, self_stream=False, self_video=False)
        values.update(kwargs)
        return NS(**values)

    def published(self):
        call = self.audit.publish.await_args
        return call.args[1], call.kwargs, '\n'.join(
            [call.args[1].title, call.args[1].description] + [f.value for f in call.args[1].fields])

    async def test_other_guilds_and_foreign_voice_channels_never_publish(self):
        original = self.member.guild
        self.member.guild = NS(id=1514871828189941881, owner_id=OWNER_ID)
        await self.activity.member_join(self.member)
        await self.activity.member_remove(self.member, self.member.guild)
        await self.activity.voice_state_update(self.member, self.state(None), self.state(self.lobby))
        self.member.guild = original
        foreign = NS(id=222, name='Do not disclose', guild=NS(id=1514871828189941881))
        await self.activity.voice_state_update(self.member, self.state(foreign), self.state(self.crew))
        self.audit.publish.assert_not_awaited()

    async def test_exact_guild_with_wrong_owner_fails_before_publish(self):
        self.guild.owner_id = 9
        with self.assertRaises(ValueError):
            await self.activity.member_join(self.member)
        with self.assertRaises(ValueError):
            await self.activity.member_remove(self.member, self.guild)
        with self.assertRaises(ValueError):
            await self.activity.voice_state_update(self.member, self.state(None), self.state(self.lobby))
        self.audit.publish.assert_not_awaited()

    async def test_voice_join_has_user_avatar_channel_ids_and_green_color(self):
        await self.activity.voice_state_update(self.member, self.state(None), self.state(self.lobby))
        embed, kwargs, text = self.published()
        self.assertEqual(kwargs['event_type'], 'voice_join')
        self.assertEqual(embed.color.value, GREEN)
        self.assertIn('<@333>', text)
        self.assertIn('<#100>', text)
        self.assertIn('`333`', text)
        self.assertIn('`100`', text)
        self.assertEqual(embed.author.name, 'El Corillo')
        self.assertEqual(embed.author.icon_url, self.member.display_avatar.url)
        self.assertEqual(embed.thumbnail.url, self.member.display_avatar.url)
        self.assertEqual(embed.timestamp, kwargs['event_time'])
        self.assertEqual(embed.timestamp.tzinfo, timezone.utc)
        self.assertIn('AST · Puerto Rico', embed.footer.text)

    async def test_voice_leave_does_not_claim_voluntary_exit_or_moderator(self):
        await self.activity.voice_state_update(self.member, self.state(self.lobby, self_mute=True), self.state(None))
        embed, kwargs, text = self.published()
        self.assertEqual(kwargs['event_type'], 'voice_leave')
        self.assertEqual(embed.color.value, RED)
        self.assertIn('no identifica al responsable', text)
        self.assertNotIn('voluntariamente', text)
        self.assertNotIn('Cambios de voz', [f.name for f in embed.fields])

    async def test_voice_move_shows_both_channels_without_inventing_mover(self):
        await self.activity.voice_state_update(self.member, self.state(self.lobby), self.state(self.crew))
        embed, kwargs, text = self.published()
        self.assertEqual(kwargs['event_type'], 'voice_move')
        self.assertEqual(embed.color.value, AMBER)
        self.assertIn('cambió de canal', text)
        self.assertIn('<#100>', text)
        self.assertIn('<#101>', text)
        self.assertIn('Canal de origen: `100`', text)
        self.assertIn('Canal de destino: `101`', text)
        self.assertIn('no identifica al responsable', text)
        self.assertNotIn('movido por', text)

    async def test_voice_flags_are_observations_and_server_actor_is_not_inferred(self):
        after = self.state(self.lobby, self_mute=True, self_deaf=True, mute=True,
                           deaf=True, self_stream=True, self_video=True)
        await self.activity.voice_state_update(self.member, self.state(self.lobby), after)
        embed, kwargs, text = self.published()
        self.assertEqual(kwargs['event_type'], 'voice_state')
        for name in ('Micrófono propio', 'Audio propio', 'Silencio del servidor',
                     'Ensordecimiento del servidor', 'Transmisión', 'Cámara'):
            self.assertIn(name, text)
        self.assertIn('no identifica al responsable', text)
        self.assertEqual(len([f for f in embed.fields if f.name == 'Cambios de voz']), 1)

    async def test_same_channel_id_and_unchanged_state_or_disconnected_noise_is_ignored(self):
        same_channel = NS(id=self.lobby.id, name='Lobby', guild=self.guild)
        await self.activity.voice_state_update(self.member, self.state(self.lobby), self.state(same_channel))
        await self.activity.voice_state_update(self.member, self.state(None), self.state(None, self_mute=True))
        self.audit.publish.assert_not_awaited()

    async def test_member_join_includes_account_date_and_distinct_runtime_event_keys(self):
        await self.activity.member_join(self.member)
        embed, kwargs, text = self.published()
        self.assertEqual(embed.color.value, GREEN)
        self.assertEqual(kwargs['event_type'], 'member_join')
        self.assertIn(f'<t:{int(self.member.created_at.timestamp())}:F>', text)
        await self.activity.member_join(self.member)
        first, second = self.audit.publish.await_args_list
        self.assertNotEqual(first.args[0], second.args[0])
        self.assertTrue(first.args[0].startswith('activity:member_join:'))

    async def test_member_leave_never_exposes_departure_reason_or_claims_moderator(self):
        self.member.reason = 'PRIVATE DEPARTURE REASON'
        self.member.actor = NS(id=919)
        await self.activity.member_remove(self.member, self.guild)
        embed, kwargs, text = self.published()
        self.assertEqual(kwargs['event_type'], 'member_leave')
        self.assertEqual(embed.color.value, RED)
        self.assertIn('no indica por sí solo', text)
        self.assertIn('exclusivo de Administración', text)
        self.assertNotIn(self.member.reason, text)
        self.assertNotIn('919', text)

    async def test_timestamp_is_captured_before_queue_wait_and_footer_is_pr_time(self):
        moment = datetime(2026, 11, 18, 14, 30, 12, tzinfo=timezone.utc)
        with patch('vice_activity.datetime') as clock:
            clock.now.return_value = moment
            await self.activity.voice_state_update(self.member, self.state(None), self.state(self.lobby))
        embed, kwargs, _ = self.published()
        self.assertEqual(kwargs['event_time'], moment)
        self.assertEqual(embed.timestamp, moment)
        self.assertIn('18/11/2026 10:30:12 AST', embed.footer.text)

    async def test_long_names_are_bounded_and_external_avatar_is_omitted(self):
        self.member.name = '@everyone ' + '**x**`' * 2000
        self.member.display_name = self.member.name
        self.member.display_avatar.url = 'https://untrusted.example/tracking-image'
        self.lobby.name = self.member.name
        await self.activity.voice_state_update(self.member, self.state(None), self.state(self.lobby))
        embed, _, text = self.published()
        self.assertLessEqual(len(embed), 6000)
        self.assertLessEqual(len(embed.author.name), 256)
        self.assertLessEqual(len(embed.title), 256)
        self.assertLessEqual(len(embed.description), 4096)
        self.assertTrue(all(len(f.value) <= 1024 for f in embed.fields))
        self.assertNotIn('@everyone', text)
        self.assertFalse(embed.thumbnail.url)
        self.assertFalse(embed.author.icon_url)


if __name__ == '__main__':
    unittest.main()
