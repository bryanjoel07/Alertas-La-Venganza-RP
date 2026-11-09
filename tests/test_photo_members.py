from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord
from photo_members import MemberDirectory,DirectoryUnavailable,MemberPicker,MentionSearch,name_key,APPLICATION_ID,GUILD_ID
from test_photos import PhotoServiceFixtures,GUILD


def raw_member(uid,nick=None):
    return {'user':{'id':str(uid),'username':f'user{uid}','global_name':None,'bot':False},'nick':nick,'roles':[],'flags':0}


class DirectoryTests(unittest.IsolatedAsyncioTestCase):
    def directory(self,pages):
        http=SimpleNamespace(get_members=AsyncMock(side_effect=pages),request=AsyncMock())
        state=SimpleNamespace(store_user=lambda data:SimpleNamespace(id=int(data['id']),name=data['username'],global_name=data.get('global_name'),bot=data.get('bot',False)))
        bot=SimpleNamespace(http=http,_connection=state)
        guild=SimpleNamespace(id=GUILD,member_count=1003)
        return MemberDirectory(bot,GUILD),guild,http

    async def test_all_pages_are_read_and_cached_without_gateway_member_intents(self):
        directory,guild,http=self.directory([[raw_member(n) for n in range(1,1001)],[raw_member(n) for n in range(1001,1004)]])
        members=await directory.load(guild)
        self.assertEqual({m.id for m in members},set(range(1,1004)))
        self.assertEqual(http.get_members.await_args_list[1].args,(GUILD,1000,1000))
        self.assertEqual(len(await directory.load(guild)),1003)
        self.assertEqual(http.get_members.await_count,2);http.request.assert_not_awaited()

    async def test_authorized_search_endpoint_is_used_when_member_listing_is_forbidden(self):
        forbidden=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'missing intent')
        directory,guild,http=self.directory(forbidden)
        guild.member_count=2
        http.request.return_value=[raw_member(1,'𝕽𝖆𝖒𝖔𝖓'),raw_member(2)]
        members=await directory.load(guild)
        self.assertEqual(len(members),2);self.assertEqual(directory.source,'member_search')
        self.assertEqual(http.request.call_args.kwargs['params'],{'query':'','limit':1000})

    async def test_failed_or_incomplete_directory_is_never_claimed_to_be_complete(self):
        forbidden=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'missing intent')
        directory,guild,http=self.directory(forbidden);http.request.side_effect=forbidden
        with self.assertRaises(DirectoryUnavailable):await directory.load(guild)
        self.assertEqual(directory.loaded_at,0);self.assertEqual(directory.last_error.reason,'permission')
        directory,guild,http=self.directory(forbidden);http.request.return_value=[raw_member(n) for n in range(1,1001)]
        with self.assertRaises(DirectoryUnavailable):await directory.load(guild)
        self.assertEqual(directory.loaded_at,0)
        directory,guild,http=self.directory(forbidden);http.request.return_value=[raw_member(1),raw_member(2)]
        with self.assertRaises(DirectoryUnavailable):await directory.load(guild)

    async def test_other_servers_are_rejected_before_reading_members(self):
        directory,_,http=self.directory([])
        with self.assertRaises(ValueError):await directory.load(SimpleNamespace(id=123))
        http.get_members.assert_not_awaited()


class MemberAccessTests(unittest.IsolatedAsyncioTestCase):
    def setup_access(self,initial=(1<<19)|(1<<23)):
        class App:
            id=APPLICATION_ID
            approximate_guild_count=1
            value=initial
            @property
            def flags(self):return discord.ApplicationFlags._from_value(self.value)
        app=App();snapshots=[]
        async def edit(**kwargs):
            self.assertEqual(len(snapshots),1,'Before-state must be durable before editing.')
            app.value=kwargs['flags'].value
        app.edit=AsyncMock(side_effect=edit)
        async def tracked(env,title,operation,*,request_id,snapshot):
            snapshots.append(await snapshot());await operation();snapshots.append(await snapshot())
        bot=SimpleNamespace(user=SimpleNamespace(id=APPLICATION_ID),application_info=AsyncMock(return_value=app),
            guilds=[SimpleNamespace(id=GUILD_ID)],intents=discord.Intents.default(),
            changes=SimpleNamespace(tracked=AsyncMock(side_effect=tracked)))
        return MemberDirectory(bot,GUILD_ID),app,snapshots

    async def test_only_member_flag_is_enabled_after_scoped_before_state_is_saved(self):
        directory,app,snapshots=self.setup_access();before=app.value
        self.assertTrue(await directory.enable_member_listing())
        self.assertEqual(app.value,before|(1<<15))
        self.assertEqual(snapshots[0],dict(application_id=str(APPLICATION_ID),flags=before,gateway_member_subscription=False))
        self.assertEqual(snapshots[1]['flags'],app.value)
        self.assertFalse(directory.bot.intents.members)
        self.assertEqual(app.edit.call_args.kwargs['reason'],'Permitir la lista de menciones en Fotos')
        self.assertFalse(await directory.enable_member_listing())
        app.edit.assert_awaited_once()

    async def test_existing_verified_or_limited_access_is_not_changed(self):
        for flags in (1<<14,1<<15):
            directory,app,_=self.setup_access(flags)
            self.assertFalse(await directory.enable_member_listing())
            app.edit.assert_not_awaited();directory.bot.changes.tracked.assert_not_awaited()

    async def test_other_bots_applications_and_large_apps_are_not_modified(self):
        directory,app,_=self.setup_access();directory.guild_id=1
        with self.assertRaises(ValueError):await directory.enable_member_listing()
        directory,app,_=self.setup_access();app.id=1
        with self.assertRaises(ValueError):await directory.enable_member_listing()
        app.edit.assert_not_awaited()
        directory,app,_=self.setup_access();app.approximate_guild_count=100
        self.assertFalse(await directory.enable_member_listing());app.edit.assert_not_awaited()

    async def test_api_refusal_is_propagated_without_changing_other_settings(self):
        directory,app,snapshots=self.setup_access();before=app.value
        app.edit.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'not permitted')
        with self.assertRaises(discord.Forbidden):await directory.enable_member_listing()
        self.assertEqual(app.value,before);self.assertEqual(len(snapshots),1)


class MemberPickerTests(PhotoServiceFixtures,unittest.IsolatedAsyncioTestCase):
    def people(self):
        people=[SimpleNamespace(id=n,name=f'user{n}',display_name=f'Persona {n:02}',global_name=None) for n in range(1,61)]
        people[29].display_name='𝕽𝖆𝖒𝖔𝖓 ⚡';people[29].name='ramonreal'
        people[39].global_name='José';people[39].display_name='𝓙𝓸𝓼𝓮́'
        return people

    async def test_open_upload_shows_the_full_paginated_directory_privately(self):
        people=self.people();self.system.member_directory.load=AsyncMock(return_value=people)
        i=self.interaction(None,user=1)
        await self.system.open_upload(i)
        result=i.response.send_message.call_args.kwargs
        self.assertTrue(result['ephemeral']);self.assertIsInstance(result['view'],MemberPicker)
        self.assertIn('60 personas',i.response.send_message.call_args.args[0]);self.assertEqual(len(result['view'].children[0].options),25)
        self.assertEqual(len(result['view'].members),60)

    async def test_search_matches_username_nickname_styled_letters_and_accents(self):
        picker=MemberPicker(self.system,1,self.people())
        picker.query='ramon';self.assertEqual([m.id for m in picker.filtered()],[30])
        picker.query='ramonreal';self.assertEqual([m.id for m in picker.filtered()],[30])
        picker.query='jose';self.assertEqual([m.id for m in picker.filtered()],[40])
        self.assertEqual(name_key('𝓙𝓸𝓼𝓮́'),'jose')
        modal=MentionSearch(picker);modal.query._value='user60'
        i=self.interaction(None,user=1);i.response.edit_message=AsyncMock()
        await modal.on_submit(i)
        self.assertEqual([o.value for o in picker.children[0].options],['60'])

    async def test_selection_survives_pagination_and_the_photo_form_preserves_chosen_people(self):
        people=self.people();picker=MemberPicker(self.system,1,people)
        i=self.interaction(None,user=1);i.response.edit_message=AsyncMock()
        select=picker.children[0];select._values=['2','4'];await select.callback(i)
        await next(c for c in picker.children if getattr(c,'label','')=='Siguiente').callback(i)
        select=picker.children[0];select._values=['28','29'];await select.callback(i)
        self.assertEqual(picker.selected,{2,4,28,29})
        await next(c for c in picker.children if getattr(c,'label','')=='Elegir foto').callback(i)
        form=i.response.send_modal.call_args.args[0]
        self.assertIsNone(form.mentions);self.assertEqual({p.id for p in form.selected_users},{2,4,28,29})
        lookup={m.id:m for m in people};self.guild.fetch_member=AsyncMock(side_effect=lambda uid:lookup[uid])
        form.photo._values=[self.source().attachments[0]];form.caption._value='Con mi gente'
        submit=self.interaction(None,user=1);await form.on_submit(submit)
        sent=self.channel.send.call_args.kwargs
        self.assertEqual({m.id for m in sent['allowed_mentions'].users},{2,4,28,29})

    async def test_total_selection_limit_is_five_across_all_pages_and_other_users_cannot_change_it(self):
        picker=MemberPicker(self.system,1,self.people());i=self.interaction(None,user=1);i.response.edit_message=AsyncMock()
        select=picker.children[0];select._values=['1','2','3','4','5'];await select.callback(i)
        await next(c for c in picker.children if getattr(c,'label','')=='Siguiente').callback(i)
        select=picker.children[0];select._values=['28'];await select.callback(i)
        self.assertEqual(picker.selected,{1,2,3,4,5})
        self.assertIn('hasta 5',i.response.edit_message.call_args.kwargs['content'])
        outsider=self.interaction(None,user=2)
        self.assertFalse(await picker.interaction_check(outsider))
        self.assertEqual(picker.selected,{1,2,3,4,5})

    async def test_private_channel_members_are_not_shown_and_no_mentions_still_work(self):
        self.system.member_directory.load=AsyncMock(return_value=self.people())
        self.channel.permissions_for=lambda user:discord.Permissions(view_channel=user.id!=30,send_messages=True)
        i=self.interaction(None,user=1);await self.system.open_upload(i)
        picker=i.response.send_message.call_args.kwargs['view']
        self.assertNotIn(30,picker.members)
        await next(c for c in picker.children if getattr(c,'label','')=='Elegir foto').callback(i)
        form=i.response.send_modal.call_args.args[0]
        self.assertIsNone(form.mentions);self.assertFalse(form.selected_users)

