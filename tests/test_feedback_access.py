import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from feedback import FeedbackSystem
from feedback_access import ACCESS_KEY,CITIZEN_ID,FIELDS,enable_citizen_panel
import test_feedback as fixtures


class CitizenAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ServiceTests.asyncSetUp(self)
        self.system.store.config(ACCESS_KEY,'')
        self.citizen=SimpleNamespace(id=CITIZEN_ID,name='Ciudadanos',permissions=discord.Permissions.none())
        self.guild.get_role=lambda rid:self.citizen if rid==CITIZEN_ID else None
        self.channel.category_id=42;self.channel.permissions_synced=True
        self.seed(False)
        self.channel.overwrites_for.side_effect=self.overwrite
        def permissions(target):
            if target.id==CITIZEN_ID:
                ow=self.overwrite(target)
                return discord.Permissions(**{name:getattr(ow,name) is True for name in (*FIELDS,'send_messages')})
            return discord.Permissions(view_channel=True,send_messages=True,embed_links=True,read_message_history=True)
        self.channel.permissions_for.side_effect=permissions
        self.channel.set_permissions=AsyncMock(side_effect=self.apply)

    def seed(self,write):
        entries=[(CITIZEN_ID,0,discord.PermissionOverwrite(view_channel=False,read_message_history=False,
            use_application_commands=False,send_messages=write,add_reactions=False,embed_links=True)),
            (10,0,discord.PermissionOverwrite(view_channel=False)),
            (1245008186440683530,0,discord.PermissionOverwrite(view_channel=True,send_messages=True)),
            (1300627506801541230,0,discord.PermissionOverwrite(read_message_history=True)),
            (77,1,discord.PermissionOverwrite(send_messages=False))]
        self.channel._overwrites=[]
        for rid,kind,ow in entries:
            allow,deny=ow.pair()
            self.channel._overwrites.append(SimpleNamespace(id=rid,type=kind,allow=allow.value,deny=deny.value))

    def overwrite(self,target):
        row=next((o for o in self.channel._overwrites if o.id==target.id and o.type==0),None)
        return discord.PermissionOverwrite.from_pair(discord.Permissions(row.allow),discord.Permissions(row.deny)) if row else discord.PermissionOverwrite()

    async def apply(self,target,*,overwrite,reason):
        self.assertEqual(target.id,CITIZEN_ID)
        # The before-state must be durable before Discord is changed.
        record=self.bot.changes.journal.rows()[0]
        self.assertEqual(record['status'],'iniciado')
        old=next((o for o in self.channel._overwrites if o.id==target.id),None)
        self.assertEqual(json.loads(record['before_json'])['target']['deny'],str(old.deny if old else 0))
        allow,deny=overwrite.pair()
        if old:old.allow,old.deny=allow.value,deny.value
        else:self.channel._overwrites.append(SimpleNamespace(id=target.id,type=0,allow=allow.value,deny=deny.value))
        self.channel.permissions_synced=False

    async def test_grant_changes_only_three_bits_and_preserves_allowed_or_denied_writing(self):
        for write in (False,True):
            with self.subTest(write=write):
                self.seed(write);self.system.store.config(ACCESS_KEY,'')
                before=[(o.id,o.type,o.allow,o.deny) for o in self.channel._overwrites if o.id!=CITIZEN_ID]
                await enable_citizen_panel(self.system)
                after=self.overwrite(self.citizen)
                self.assertTrue(all(getattr(after,name) is True for name in FIELDS))
                self.assertIs(after.send_messages,write)
                self.assertFalse(after.add_reactions);self.assertTrue(after.embed_links)
                self.assertEqual([(o.id,o.type,o.allow,o.deny) for o in self.channel._overwrites if o.id!=CITIZEN_ID],before)
                self.assertEqual(self.citizen.permissions.value,0)
                self.assertEqual(self.system.store.config(ACCESS_KEY),'complete')
                self.assertEqual(self.bot.changes.journal.rows()[0]['status'],'completado')
                self.channel.edit.assert_not_called();self.channel.purge.assert_not_called()

    async def test_restart_does_not_reapply_access_or_overwrite_later_manual_choices(self):
        await enable_citizen_panel(self.system)
        self.channel.set_permissions.assert_awaited_once()
        # Administration can change the access later without a periodic override.
        row=next(o for o in self.channel._overwrites if o.id==CITIZEN_ID)
        row.allow=0
        restarted=FeedbackSystem(self.bot,self.path,10);restarted.store.initialize()
        await enable_citizen_panel(restarted)
        self.channel.set_permissions.assert_awaited_once()
        self.assertEqual(row.allow,0)

    async def test_missing_overwrite_creates_only_citizen_access_and_keeps_writing_inherited(self):
        self.channel._overwrites=[o for o in self.channel._overwrites if o.id!=CITIZEN_ID]
        before=[(o.id,o.type,o.allow,o.deny) for o in self.channel._overwrites]
        await enable_citizen_panel(self.system)
        actual=self.overwrite(self.citizen)
        self.assertTrue(all(getattr(actual,name) is True for name in FIELDS))
        self.assertIsNone(actual.send_messages)
        self.assertEqual([(o.id,o.type,o.allow,o.deny) for o in self.channel._overwrites if o.id!=CITIZEN_ID],before)
        saved=json.loads(self.bot.changes.journal.rows()[0]['before_json'])
        self.assertFalse(any(o['id']==CITIZEN_ID for o in saved['overwrites']))

    async def test_discord_failure_keeps_backup_and_does_not_mark_request_complete(self):
        before=[(o.id,o.type,o.allow,o.deny) for o in self.channel._overwrites]
        self.channel.set_permissions.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'denied')
        with self.assertRaises(discord.Forbidden):await enable_citizen_panel(self.system)
        self.assertEqual(self.system.store.config(ACCESS_KEY),'')
        self.assertEqual([(o.id,o.type,o.allow,o.deny) for o in self.channel._overwrites],before)
        self.assertEqual(self.bot.changes.journal.rows()[0]['status'],'fallido')

    async def test_missing_citizen_role_does_not_guess_or_mutate_another_role(self):
        self.guild.get_role=lambda rid:None
        with self.assertRaisesRegex(ValueError,'Ciudadanos'):await enable_citizen_panel(self.system)
        self.channel.set_permissions.assert_not_awaited()
        self.assertEqual(self.system.store.config(ACCESS_KEY),'')

    async def test_regular_citizen_can_open_the_existing_feedback_form_after_grant(self):
        self.members[1].roles=[self.citizen]
        await self.system.ready()
        self.assertTrue(self.channel.permissions_for(self.citizen).view_channel)
        self.assertFalse(self.members[1].guild_permissions.administrator)
        i=fixtures.ServiceTests.interaction(self)
        await self.system.handle(i,'start',0)
        self.assertEqual([c.label for c in i.followup.send.call_args.kwargs['view'].children],
            ['Valorar un ticket','Me atendieron fuera de tickets'])
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
        self.assertFalse(self.system.store.rows())
