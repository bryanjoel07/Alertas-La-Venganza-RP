"""Security and lifecycle of registered temporary voice rooms."""
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from esschino import StudioStore
from vice_design import GUILD_ID, BOT_ID, OWNER_ID
from vice_voice import TempVoice, VoicePanel, VoiceStore, NEW_GRACE, EMPTY_GRACE


async def history(items):
    for item in items:
        yield item


class TempVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name)/'vice.sqlite3'
        store = StudioStore(path)
        store.initialize()
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id, self.guild.unavailable = GUILD_ID, OWNER_ID, False
        self.guild.default_role = MagicMock(spec=discord.Role)
        self.guild.default_role.id = GUILD_ID
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id = BOT_ID
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.bot.intents.voice_states = True
        self.bot.is_ready.return_value = True
        self.bot.get_guild.return_value = self.guild
        self.owner = self.member(77)
        self.interaction = NS(guild=self.guild, guild_id=GUILD_ID, user=self.owner, id=123)
        self.category = MagicMock(spec=discord.CategoryChannel)
        self.category.id, self.category.guild = 501, self.guild
        self.channels = {501:self.category}
        self.guild.get_channel.side_effect = lambda cid:self.channels.get(cid)
        self.guild.audit_logs = lambda **kw: history([])
        self.roles = {}
        for idx,key in enumerate(('founder','admin','mod'),100):
            role = MagicMock(spec=discord.Role)
            role.id = idx
            self.roles[key] = role
            store.put('role:'+key,idx)
        store.put('category:tempvoice',501)
        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('Wrong guild')
        def authorize(interaction):
            validate(interaction.guild)
            if interaction.guild_id != GUILD_ID or interaction.user.bot:
                raise ValueError('Wrong interaction')
        async def tracked(kind,title,operation,request,snapshot=None):
            if snapshot:
                await snapshot()
            result=await operation()
            if snapshot:
                await snapshot()
            return result
        async def call(name,*args):
            return getattr(store,name)(*args)
        self.system = NS(bot=self.bot,path=path,store=store,validate_guild=validate,
            authorize=authorize,track=AsyncMock(side_effect=tracked),call=call,
            role=lambda guild,key:self.roles.get(key),channel_cache={},channel_id=lambda key:store.get('channel:'+key))
        self.manager = TempVoice(self.system)
        await self.manager.start()
        self.manager.configured = True
        async def create(name, **values):
            channel=self.voice(601+len([c for c in self.channels.values() if isinstance(c,discord.VoiceChannel)]))
            channel.name=name
            channel.overwrites=values['overwrites']
            channel.user_limit=values['user_limit']
            self.channels[channel.id]=channel
            return channel
        self.guild.create_voice_channel=AsyncMock(side_effect=create)

    def member(self, uid):
        member=MagicMock(spec=discord.Member)
        member.id,member.guild,member.bot=uid,self.guild,False
        member.display_name='Corillo '+str(uid)
        member.guild_permissions=discord.Permissions.none()
        member.roles=[]
        member.voice=None
        member.move_to=AsyncMock()
        return member

    def voice(self,cid):
        channel=MagicMock(spec=discord.VoiceChannel)
        channel.id,channel.guild,channel.category_id=cid,self.guild,501
        channel.name='Sala'
        channel.user_limit=6
        channel.voice_states={}
        channel.overwrites={}
        channel.overwrites_for.side_effect=lambda target:channel.overwrites.get(target,discord.PermissionOverwrite())
        channel.edit=AsyncMock()
        channel.delete=AsyncMock()
        async def permissions(target,overwrite,**kw):
            channel.overwrites[target]=overwrite
        channel.set_permissions=AsyncMock(side_effect=permissions)
        return channel

    async def created(self):
        channel=await self.manager.create_room(self.interaction)
        return self.manager.store.owned(self.owner.id),channel

    async def test_public_controls_are_persistent_and_unique(self):
        panel=VoicePanel(self.manager)
        self.assertTrue(panel.is_persistent())
        self.assertEqual(len({c.custom_id for c in panel.children}),2)
        self.assertEqual([c.label for c in panel.children],['Crear mi sala','Administrar mi sala'])

    async def test_creator_gets_voice_only_and_is_not_moved(self):
        row,channel=await self.created()
        self.assertEqual(row['channel'],channel.id)
        rules=self.guild.create_voice_channel.await_args.kwargs['overwrites']
        self.assertTrue(rules[self.owner].connect)
        self.assertFalse(rules[self.owner].send_messages)
        self.assertFalse(rules[self.guild.default_role].send_messages)
        for flag in ('manage_roles','manage_channels','move_members','manage_webhooks'):
            self.assertFalse(getattr(rules[self.owner],flag))
        self.owner.move_to.assert_not_awaited()
        self.system.track.assert_awaited_once()

    async def test_one_room_per_owner_and_concurrent_calls_reuse_it(self):
        import asyncio
        first,second=await asyncio.gather(self.manager.create_room(self.interaction),self.manager.create_room(self.interaction))
        self.assertEqual(first.id,second.id)
        self.guild.create_voice_channel.assert_awaited_once()

    async def test_wrong_guild_and_bot_cannot_create(self):
        self.interaction.guild_id=1514871828189941881
        with self.assertRaises(ValueError):await self.manager.create_room(self.interaction)
        self.interaction.guild_id=GUILD_ID
        self.owner.bot=True
        with self.assertRaises(ValueError):await self.manager.create_room(self.interaction)
        self.guild.create_voice_channel.assert_not_awaited()

    async def test_other_owner_and_stale_controls_cannot_modify_room(self):
        _,channel=await self.created()
        other=NS(guild=self.guild,guild_id=GUILD_ID,user=self.member(88),id=124)
        with self.assertRaises(ValueError):await self.manager.set_locked(other,channel.id,True)
        with self.assertRaises(ValueError):await self.manager.set_limit(self.interaction,channel.id+1,'8')
        channel.edit.assert_not_awaited()
        channel.set_permissions.assert_not_awaited()

    async def test_lock_preserves_text_denial_and_invited_member_access(self):
        _,channel=await self.created()
        guest=self.member(88)
        self.guild.fetch_member=AsyncMock(return_value=guest)
        await self.manager.set_access(self.interaction,channel.id,88,True)
        await self.manager.set_locked(self.interaction,channel.id,True)
        self.assertFalse(channel.overwrites[self.guild.default_role].connect)
        self.assertFalse(channel.overwrites[self.guild.default_role].send_messages)
        self.assertTrue(channel.overwrites[guest].connect)
        self.assertTrue(channel.overwrites[self.owner].connect)

    async def test_revoke_disconnects_only_from_owned_room(self):
        _,channel=await self.created()
        guest=self.member(88)
        self.guild.fetch_member=AsyncMock(return_value=guest)
        guest.voice=NS(channel=NS(id=999))
        await self.manager.set_access(self.interaction,channel.id,88,False)
        guest.move_to.assert_not_awaited()
        guest.voice=NS(channel=channel)
        await self.manager.set_access(self.interaction,channel.id,88,False)
        guest.move_to.assert_awaited_once_with(None,reason='El creador retiró el acceso a su sala temporal')
        self.assertFalse(channel.overwrites[guest].connect)

    async def test_owner_cannot_revoke_moderator_admin_bot_or_self(self):
        _,channel=await self.created()
        targets=[self.owner,self.member(BOT_ID),self.member(OWNER_ID),self.member(88),self.member(89)]
        targets[-2].roles=[self.roles['mod']]
        targets[-1].guild_permissions=discord.Permissions(administrator=True)
        for target in targets:
            self.guild.fetch_member=AsyncMock(return_value=target)
            with self.assertRaises(ValueError):await self.manager.set_access(self.interaction,channel.id,target.id,False)
            target.move_to.assert_not_awaited()
        channel.set_permissions.assert_not_awaited()

    async def test_limit_validation_and_rename_cooldown(self):
        _,channel=await self.created()
        for value in ('0','21','x','-1'):
            with self.assertRaises(ValueError):await self.manager.set_limit(self.interaction,channel.id,value)
        await self.manager.set_limit(self.interaction,channel.id,'8')
        self.assertEqual(channel.edit.await_args.kwargs['user_limit'],8)
        await self.manager.rename(self.interaction,channel.id,'Mi crew')
        with self.assertRaises(ValueError):await self.manager.rename(self.interaction,channel.id,'Otra crew')

    async def test_creation_cooldown_and_capacity_survive_restart(self):
        row,_=await self.created()
        self.manager.store.update(row['token'],state='closed')
        replacement=VoiceStore(self.system.path)
        replacement.initialize()
        with self.assertRaises(ValueError):replacement.reserve(self.owner.id,time.time())
        for uid in range(200,220):replacement.reserve(uid,time.time())
        with self.assertRaises(ValueError):replacement.reserve(999,time.time())

    async def test_uncached_voice_participant_prevents_deletion(self):
        row,channel=await self.created()
        channel.members=[]
        channel.voice_states={999:NS(channel=channel)}
        await self.manager.inspect_room(self.guild,row,row['created']+999)
        channel.delete.assert_not_awaited()
        current=self.manager.store.get(row['token'])
        self.assertTrue(current['used'])
        self.assertIsNone(current['empty_since'])

    async def test_unused_room_has_two_minute_grace_and_only_then_deleted(self):
        row,channel=await self.created()
        await self.manager.inspect_room(self.guild,row,row['created']+NEW_GRACE-1)
        channel.delete.assert_not_awaited()
        await self.manager.inspect_room(self.guild,row,row['created']+NEW_GRACE+1)
        channel.delete.assert_awaited_once()
        self.assertEqual(self.manager.store.get(row['token'])['state'],'closed')

    async def test_used_room_grace_resets_after_reentry_and_survives_restart(self):
        row,channel=await self.created()
        self.manager.store.update(row['token'],used=1,empty_since=None)
        replacement=TempVoice(self.system)
        await replacement.start()
        replacement.configured=True
        row=replacement.store.get(row['token'])
        await replacement.inspect_room(self.guild,row,1000)
        row=replacement.store.get(row['token'])
        self.assertEqual(row['empty_since'],1000)
        channel.voice_states={888:NS(channel=channel)}
        await replacement.inspect_room(self.guild,row,1100)
        self.assertIsNone(replacement.store.get(row['token'])['empty_since'])
        channel.delete.assert_not_awaited()

    async def test_moved_or_wrong_type_channel_is_never_deleted(self):
        row,channel=await self.created()
        channel.category_id=999
        await self.manager.inspect_room(self.guild,row,row['created']+999)
        channel.delete.assert_not_awaited()
        text=MagicMock(spec=discord.TextChannel)
        text.id,text.guild,text.category_id=channel.id,self.guild,501
        text.delete=AsyncMock()
        self.channels[channel.id]=text
        await self.manager.inspect_room(self.guild,row,row['created']+999)
        text.delete.assert_not_awaited()

    async def test_gateway_unready_or_unavailable_never_deletes(self):
        row,channel=await self.created()
        self.bot.is_ready.return_value=False
        await self.manager.inspect_room(self.guild,row,row['created']+999)
        self.bot.is_ready.return_value=True
        self.guild.unavailable=True
        await self.manager.inspect_room(self.guild,row,row['created']+999)
        channel.delete.assert_not_awaited()

    async def test_missing_cache_but_existing_http_channel_is_not_deleted(self):
        row,channel=await self.created()
        self.channels.pop(channel.id)
        self.guild.fetch_channel=AsyncMock(return_value=channel)
        await self.manager.inspect_room(self.guild,row,row['created']+999)
        channel.delete.assert_not_awaited()
        self.assertEqual(self.manager.store.get(row['token'])['state'],'active')

    async def test_failed_delete_does_not_close_the_registry(self):
        row,channel=await self.created()
        channel.delete.side_effect=RuntimeError('temporary failure')
        with self.assertRaises(RuntimeError):await self.manager.inspect_room(self.guild,row,row['created']+999)
        self.assertEqual(self.manager.store.get(row['token'])['state'],'active')

    async def test_join_while_before_snapshot_is_saved_cancels_deletion(self):
        row,channel=await self.created()
        async def tracked(kind,title,operation,request,snapshot=None):
            await snapshot()
            channel.voice_states={888:NS(channel=channel)}
            return await operation()
        self.system.track.side_effect=tracked
        await self.manager.inspect_room(self.guild,row,row['created']+999)
        channel.delete.assert_not_awaited()
        self.assertEqual(self.manager.store.get(row['token'])['state'],'active')

    async def test_exact_room_snapshot_records_permissions_and_closed_state(self):
        row,channel=await self.created()
        snapshots=[]
        async def tracked(kind,title,operation,request,snapshot=None):
            snapshots.append(await snapshot())
            result=await operation()
            snapshots.append(await snapshot())
            return result
        self.system.track.side_effect=tracked
        await self.manager.inspect_room(self.guild,row,row['created']+999)
        self.assertEqual(snapshots[0]['room']['state'],'active')
        self.assertEqual(snapshots[0]['channel']['id'],channel.id)
        self.assertEqual(len(snapshots[0]['channel']['overwrites']),6)
        self.assertEqual(snapshots[1]['room']['state'],'closed')

    async def test_voice_event_does_not_touch_permanent_or_other_guild_channels(self):
        permanent=self.voice(900)
        self.channels[900]=permanent
        await self.manager.voice_state_update(self.owner,NS(channel=permanent),NS(channel=None))
        permanent.delete.assert_not_awaited()
        self.owner.guild=NS(id=1514871828189941881)
        await self.manager.voice_state_update(self.owner,NS(channel=permanent),NS(channel=None))
        permanent.delete.assert_not_awaited()

    async def test_pending_creation_recovers_only_exact_bot_nonce(self):
        row,_=self.manager.store.reserve(77,time.time())
        channel=self.voice(700)
        self.channels[700]=channel
        bad=NS(user=NS(id=123),reason='VICE_TEMP:'+row['token'],target=NS(id=700))
        self.guild.audit_logs=lambda **kw:history([bad])
        self.assertIsNone(await self.manager.reconcile_pending(self.guild,row))
        good=NS(user=NS(id=BOT_ID),reason='VICE_TEMP:'+row['token'],target=NS(id=700))
        self.guild.audit_logs=lambda **kw:history([good])
        result=await self.manager.reconcile_pending(self.guild,row)
        self.assertEqual(result.id,700)
        self.assertEqual(self.manager.store.get(row['token'])['channel'],700)
        self.guild.create_voice_channel.assert_not_awaited()

    async def test_create_failure_leaves_reserved_nonce_and_does_not_duplicate(self):
        self.guild.create_voice_channel.side_effect=RuntimeError('network uncertainty')
        with self.assertRaises(RuntimeError):await self.manager.create_room(self.interaction)
        with self.assertRaises(ValueError):await self.manager.create_room(self.interaction)
        self.guild.create_voice_channel.assert_awaited_once()
        self.assertEqual(self.manager.store.owned(77)['state'],'creating')


if __name__=='__main__':
    unittest.main()
