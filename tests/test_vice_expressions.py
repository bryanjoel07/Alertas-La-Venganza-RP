"""Capacity, ownership and retry guarantees for the district emoji expansion."""
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_expressions import (
    ALL_ANIMATED_EMOJIS, ANIMATED_EMOJIS, EMOJI_PACKS, EXPRESSIONS_VERSION,
    HYPE_ANIMATED_EMOJIS, MASCOT_ANIMATED_EMOJIS, MAX_HYPE_EMOJIS, MAX_MASCOT_EMOJIS,
    STATIC_EMOJIS, install_expansion,
)


class ExpressionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.assets = Path(self.tmp.name)
        self.total = len(STATIC_EMOJIS) + len(ALL_ANIMATED_EMOJIS)
        for animated, names, folder, extension in EMOJI_PACKS:
            header = b'GIF89a' if animated else b'\x89PNG\r\n\x1a\n'
            base = self.assets / folder
            base.mkdir(parents=True)
            for name in names:
                (base / (name + extension)).write_bytes(header + b'test-only-format-payload')
        patcher = patch('vice_expressions.ASSETS', self.assets)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config, self.existing, self.snapshots = {}, [], []
        self.guild = NS(id=GUILD_ID, owner_id=OWNER_ID, emoji_limit=50)
        self.guild.fetch_emojis = AsyncMock(side_effect=lambda: list(self.existing))
        async def create(**kwargs):
            emoji = NS(id=10000 + len(self.existing), name=kwargs['name'],
                       animated=kwargs['image'].startswith(b'GIF'), user=NS(id=BOT_ID), roles=[])
            self.existing.append(emoji)
            return emoji
        self.guild.create_custom_emoji = AsyncMock(side_effect=create)
        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')
        async def call(method, key, value):
            self.assertEqual(method, 'put')
            self.config[key] = value
        async def track(kind, title, operation, request, snapshot=None):
            before = await snapshot()
            result = await operation()
            self.snapshots.append((kind, before, await snapshot()))
            return result
        self.system = NS(bot=NS(get_guild=lambda _: self.guild), validate_guild=validate,
            store=NS(get=self.config.get), call=AsyncMock(side_effect=call), track=AsyncMock(side_effect=track))

    def existing_emoji(self, index, *, animated=False, name=None, author=OWNER_ID):
        return NS(id=100 + index, name=name or f'existing_{index}', animated=animated,
                  user=NS(id=author), roles=[NS(id=500)])

    async def test_foreign_or_missing_guild_rejected_before_any_api_call(self):
        actual = self.guild
        for guild in (None, NS(id=1514871828189941881, owner_id=OWNER_ID),
                      NS(id=GUILD_ID, owner_id=123)):
            self.system.bot.get_guild = lambda _, value=guild: value
            with self.subTest(guild=guild), self.assertRaises(ValueError):
                await install_expansion(self.system)
        actual.fetch_emojis.assert_not_awaited()
        actual.create_custom_emoji.assert_not_awaited()
        self.system.track.assert_not_awaited()

    async def test_each_format_has_independent_quota_and_preflight_never_partially_uploads(self):
        self.guild.emoji_limit = max(len(STATIC_EMOJIS), len(ALL_ANIMATED_EMOJIS))
        for animated, names in ((False, STATIC_EMOJIS), (True, ALL_ANIMATED_EMOJIS)):
            occupied = self.guild.emoji_limit - len(names) + 1
            self.existing[:] = [self.existing_emoji(index, animated=animated)
                                for index in range(occupied)]
            with self.subTest(animated=animated), self.assertRaisesRegex(ValueError, 'espacios'):
                await install_expansion(self.system)
            self.guild.create_custom_emoji.assert_not_awaited()
            self.system.track.assert_not_awaited()
            self.assertEqual(self.config, {})
        # Each format has its own quota, even when the combined count exceeds it.
        self.existing.clear()
        await install_expansion(self.system)
        self.assertEqual(sum(e.animated for e in self.existing), len(ALL_ANIMATED_EMOJIS))
        self.assertEqual(sum(not e.animated for e in self.existing), len(STATIC_EMOJIS))

    async def test_upgrade_sums_both_new_animated_packs_before_upload_and_preserves_previous(self):
        previous_animated = ANIMATED_EMOJIS + MASCOT_ANIMATED_EMOJIS + HYPE_ANIMATED_EMOJIS
        for animated, names in ((False, STATIC_EMOJIS), (True, previous_animated)):
            for name in names:
                emoji = self.existing_emoji(len(self.existing), animated=animated,
                                            name=name, author=BOT_ID)
                self.existing.append(emoji)
                self.config['emoji:' + name] = emoji.id
        self.config['emoji_expansion_release'] = 'vice-expressions-expanded-v2'
        previous = list(self.existing)
        previous_config = dict(self.config)
        new_names = MAX_MASCOT_EMOJIS + MAX_HYPE_EMOJIS

        # Ten free animated slots fit either six-emoji pack, but not both packs.
        self.guild.emoji_limit = len(previous_animated) + len(new_names) - 2
        with self.assertRaisesRegex(ValueError, 'espacios'):
            await install_expansion(self.system)
        self.guild.create_custom_emoji.assert_not_awaited()
        self.system.track.assert_not_awaited()
        self.system.call.assert_not_awaited()
        self.assertEqual(self.existing, previous)
        self.assertEqual(self.config, previous_config)

        # Exactly enough animated slots permit the whole upgrade in one tracked operation.
        self.guild.emoji_limit = len(ALL_ANIMATED_EMOJIS)
        await install_expansion(self.system)
        self.assertEqual(self.guild.create_custom_emoji.await_count, len(new_names))
        self.assertEqual({call.kwargs['name'] for call in self.guild.create_custom_emoji.await_args_list},
                         set(new_names))
        self.assertEqual(len(self.existing), self.total)
        for index, emoji in enumerate(previous):
            self.assertIs(self.existing[index], emoji)
            self.assertEqual(self.config['emoji:' + emoji.name], emoji.id)
            self.assertEqual([role.id for role in emoji.roles], [500])
        self.system.track.assert_awaited_once()
        self.assertEqual(len(self.snapshots[0][1]['emojis']), len(previous))
        self.assertEqual(self.config['emoji_expansion_release'], EXPRESSIONS_VERSION)
        self.guild.fetch_emojis.reset_mock()
        self.guild.create_custom_emoji.reset_mock()
        await install_expansion(self.system)
        self.guild.fetch_emojis.assert_not_awaited()
        self.guild.create_custom_emoji.assert_not_awaited()
        self.assertEqual(len(self.existing), self.total)

    async def test_existing_foreign_emoji_is_preserved_and_new_emojis_are_unrestricted(self):
        foreign = self.existing_emoji(1, name=STATIC_EMOJIS[0])
        self.existing.append(foreign)
        await install_expansion(self.system)
        self.assertIs(self.existing[0], foreign)
        self.assertEqual(foreign.roles[0].id, 500)
        self.assertEqual(len(self.existing), self.total + 1)
        self.assertEqual(self.guild.create_custom_emoji.await_count, self.total)
        for call in self.guild.create_custom_emoji.await_args_list:
            self.assertEqual(call.kwargs['roles'], [])
        kind, before, after = self.snapshots[0]
        self.assertEqual(kind, 'EXPRESSIONS_EXPAND')
        self.assertEqual(before['emojis'], [dict(id=foreign.id, name=foreign.name,
                                               animated=False, roles=[500])])
        self.assertEqual(len(after['emojis']), self.total + 1)

    async def test_retry_recovers_upload_before_database_write_and_marker_skips_api(self):
        put = self.system.call.side_effect
        failed = False
        async def fail_once(method, key, value):
            nonlocal failed
            if key == 'emoji:' + STATIC_EMOJIS[0] and not failed:
                failed = True
                raise OSError('simulated database interruption after Discord upload')
            return await put(method, key, value)
        self.system.call.side_effect = fail_once
        with self.assertRaises(OSError):
            await install_expansion(self.system)
        first_id = self.existing[0].id
        self.assertEqual(len(self.existing), 1)
        self.assertNotIn('emoji_expansion_release', self.config)
        await install_expansion(self.system)
        self.assertEqual(len(self.existing), self.total)
        self.assertEqual(self.config['emoji:' + STATIC_EMOJIS[0]], first_id)
        self.assertEqual(self.guild.create_custom_emoji.await_count, self.total)
        self.assertEqual(self.config['emoji_expansion_release'], EXPRESSIONS_VERSION)
        self.guild.fetch_emojis.reset_mock()
        self.guild.create_custom_emoji.reset_mock()
        await install_expansion(self.system)
        self.guild.fetch_emojis.assert_not_awaited()
        self.guild.create_custom_emoji.assert_not_awaited()

    async def test_invalid_animated_payload_or_registered_format_aborts_without_upload(self):
        path = self.assets / 'emojis-v4' / 'hype' / (MAX_HYPE_EMOJIS[-1] + '.gif')
        for data in (b'not-a-gif', b'GIF89a' + b'x' * (256 * 1024)):
            path.write_bytes(data)
            with self.subTest(size=len(data)), self.assertRaisesRegex(ValueError, 'Formato'):
                await install_expansion(self.system)
            self.guild.create_custom_emoji.assert_not_awaited()
        path.write_bytes(b'GIF89a' + b'test-only-format-payload')
        self.existing.append(self.existing_emoji(1, animated=False, name=ANIMATED_EMOJIS[0], author=BOT_ID))
        with self.assertRaisesRegex(ValueError, 'formato'):
            await install_expansion(self.system)
        self.guild.create_custom_emoji.assert_not_awaited()
        self.system.track.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
