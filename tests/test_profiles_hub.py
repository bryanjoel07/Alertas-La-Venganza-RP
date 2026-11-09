import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
from profiles_hub import NAME, ProfileTree, ensure_profiles, profile_overwrites


class ProfilesHubTests(unittest.IsolatedAsyncioTestCase):
    def guild(self):
        guild = MagicMock()
        guild.default_role.id = 1
        guild.default_role.permissions = discord.Permissions.none()
        guild.me.id = 2
        return guild

    async def test_inherited_player_allow_cannot_bypass_read_only(self):
        guild = self.guild()
        player = MagicMock()
        player.id = 3
        player.permissions = discord.Permissions.none()
        inherited = {player: discord.PermissionOverwrite(send_messages=True, view_channel=True)}
        result = profile_overwrites(guild, inherited)
        self.assertFalse(result[player].send_messages)
        self.assertFalse(result[player].send_messages_in_threads)
        self.assertTrue(result[player].use_application_commands)
        self.assertTrue(result[guild.default_role].view_channel)
        self.assertFalse(result[guild.default_role].send_messages)
        self.assertTrue(result[guild.me].send_messages)
        self.assertTrue(inherited[player].send_messages)

    async def test_existing_channel_and_guide_are_reused(self):
        guild = self.guild()
        category = SimpleNamespace(id=20)
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 21
        channel.category_id = 20
        channel.overwrites = profile_overwrites(guild, {})
        channel.permissions_for.return_value = discord.Permissions.none()
        guild.get_channel.return_value = channel
        economy = MagicMock()
        economy.delivery.category.return_value = category
        economy.store.config.side_effect = lambda key: {'profiles_channel': '21', 'profiles_guide': '22'}.get(key, '')
        await ensure_profiles(economy, guild)
        guild.create_text_channel.assert_not_called()
        channel.send.assert_not_called()
        channel.edit.assert_not_called()

    async def test_create_channel_with_guide_and_save_ids(self):
        guild = self.guild()
        category = SimpleNamespace(id=20, name='La Venganza', overwrites={})
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 21
        channel.category_id = 20
        channel.name = NAME
        channel.overwrites = profile_overwrites(guild, {})
        channel.permissions_for.return_value = discord.Permissions.none()
        channel.send = AsyncMock(return_value=SimpleNamespace(id=22))
        guild.fetch_channels = AsyncMock(return_value=[])
        guild.create_text_channel = AsyncMock(return_value=channel)
        economy = MagicMock()
        economy.delivery.category.return_value = category
        economy.store.config.return_value = ''
        await ensure_profiles(economy, guild)
        permissions = guild.create_text_channel.call_args.kwargs['overwrites']
        self.assertFalse(permissions[guild.default_role].send_messages)
        self.assertTrue(permissions[guild.default_role].use_application_commands)
        self.assertIs(guild.create_text_channel.call_args.kwargs['category'], category)
        economy.store.runtime_config.assert_any_call('profiles_channel', 21)
        economy.store.runtime_config.assert_any_call('profiles_guide', 22)

    async def test_only_profile_command_is_accepted_in_hub(self):
        tree = SimpleNamespace(client=MagicMock())
        tree.client.economy.ready = True
        tree.client.economy.store.config.return_value = '21'
        interaction = SimpleNamespace(channel_id=21, command=SimpleNamespace(name='perfil'),
                                      response=SimpleNamespace(send_message=AsyncMock()))
        self.assertTrue(await ProfileTree.interaction_check(tree, interaction))
        interaction.command.name = 'comprar'
        self.assertFalse(await ProfileTree.interaction_check(tree, interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        interaction.channel_id = 99
        self.assertTrue(await ProfileTree.interaction_check(tree, interaction))
