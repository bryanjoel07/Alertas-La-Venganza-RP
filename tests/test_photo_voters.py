from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

import discord

from backup import snapshot
from photo_store import PhotoStore
from photo_members import DirectoryUnavailable
from photos import PhotoButton,PhotoControls,PhotoVotersPanel,FOTOS_CHANNEL
from test_photos import PhotoServiceFixtures,BASE,GUILD
import test_photos as fixtures


class PhotoVoterStoreTests(unittest.TestCase):
    photo=fixtures.PhotoStoreTests.photo

    def setUp(self):
        fixtures.PhotoStoreTests.setUp(self)

    def test_voters_are_unique_scoped_to_the_photo_and_ordered_by_time_then_id(self):
        entry=self.photo();other=self.photo(source=11,attachment=21)
        self.store.vote(entry,20,now=BASE+2);self.store.vote(entry,10,now=BASE+2)
        self.store.vote(entry,30,now=BASE+1);self.store.vote(entry,20,now=BASE+3)
        self.store.vote(other,40,now=BASE+2)
        self.assertEqual(self.store.voters(entry),dict(total=3,page=0,pages=1,users=[30,10,20]))
        self.store.vote(entry,10,False,now=BASE+4)
        self.assertEqual(self.store.voters(entry)['users'],[30,20])
        self.assertEqual(self.store.voters(other)['users'],[40])

    def test_pages_are_bounded_and_reclamped_after_vote_removals(self):
        entry=self.photo()
        for uid in range(100,127):self.store.vote(entry,uid,now=BASE+1)
        first=self.store.voters(entry,-1);last=self.store.voters(entry,1000000)
        self.assertEqual(first['users'],list(range(100,125)))
        self.assertEqual(last,dict(total=27,page=1,pages=2,users=[125,126]))
        for uid in (125,126):self.store.vote(entry,uid,False,now=BASE+2)
        self.assertEqual(self.store.voters(entry,1)['page'],0)
        self.assertEqual(self.store.voters(999),dict(total=0,page=0,pages=1,users=[]))

    def test_reading_closed_week_voters_preserves_results_and_survives_backup(self):
        entry=self.photo();self.store.vote(entry,10,now=BASE+1)
        self.store.freeze(self.week,self.end)
        before=self.store.entry(entry);week=self.store.week(self.week)
        self.assertEqual(self.store.voters(entry)['users'],[10])
        self.assertEqual(self.store.entry(entry),before);self.assertEqual(self.store.week(self.week),week)
        target=self.path.with_name('voters-backup.db');snapshot(self.path,target)
        restored=PhotoStore(target)
        self.assertEqual(restored.voters(entry)['users'],[10])


class PhotoVotersTests(PhotoServiceFixtures,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await PhotoServiceFixtures.asyncSetUp(self)
        self.guild.fetch_member=AsyncMock(side_effect=lambda uid:self.named_user(uid))
        self.bot.fetch_user=AsyncMock(side_effect=lambda uid:self.named_user(uid))

    def named_user(self,uid,name=None,display=None):
        return SimpleNamespace(id=uid,name=name or f'jugador{uid}',display_name=display or f'Jugador {uid}',global_name=None)

    def interaction(self,*args,**kwargs):
        i=PhotoServiceFixtures.interaction(self,*args,**kwargs)
        i.edit_original_response=AsyncMock()
        return i

    async def photo(self):
        original=self.source()
        i=self.interaction(None,user=1)
        await self.system.submit_upload(i,original.attachments[0],'Mi foto')
        row=self.system.store.entries()[0]
        return row,self.messages[row['control']]

    def response(self,i):
        return i.followup.send.call_args or i.response.send_message.call_args

    async def panel(self,row,message,user=2):
        i=self.interaction(message,user=user)
        await self.system.show_voters(i,row['id'])
        return i,self.response(i).kwargs['view']

    async def test_button_opens_private_names_and_does_not_add_or_remove_any_vote(self):
        row,message=await self.photo();entry=row['id']
        self.system.store.vote(entry,2,now=BASE+1);self.system.store.vote(entry,3,now=BASE+2)
        message.edit.reset_mock();self.channel.send.reset_mock()
        before=self.system.store.entry(entry)
        i=self.interaction(message);i.client.photos=self.system;i.response.is_done.return_value=True
        await PhotoButton(entry,'voters').callback(i)
        response=self.response(i)
        self.assertTrue(response.kwargs['ephemeral']);self.assertIsInstance(response.kwargs['view'],PhotoVotersPanel)
        text=response.kwargs['embed'].description
        self.assertIn('Jugador 2',text);self.assertIn('@jugador2',text)
        self.assertIn('Jugador 3',text);self.assertIn('@jugador3',text);self.assertIn('**2 votos**',text)
        self.assertNotIn('<@',text)
        self.assertEqual(response.kwargs['allowed_mentions'].to_dict(),discord.AllowedMentions.none().to_dict())
        self.assertEqual(self.system.store.entry(entry),before)
        self.assertEqual(self.system.store.voters(entry)['users'],[2,3])
        message.edit.assert_not_awaited();self.channel.send.assert_not_awaited()

    async def test_empty_panel_explains_no_votes_and_can_refresh_after_someone_votes(self):
        row,message=await self.photo();i,panel=await self.panel(row,message)
        self.assertIn('todavía no tiene votos',self.response(i).kwargs['embed'].description)
        self.assertTrue(panel.previous.disabled);self.assertTrue(panel.next.disabled)
        self.system.store.vote(row['id'],3,now=BASE+1)
        click=self.interaction(SimpleNamespace(id=999999))
        await panel.refresh.callback(click)
        result=click.edit_original_response.call_args
        self.assertIn('@jugador3',result.kwargs['embed'].description)
        self.assertIn('**1 voto**',result.kwargs['embed'].description)
        self.assertEqual(result.kwargs['allowed_mentions'].to_dict(),discord.AllowedMentions.none().to_dict())
        click.response.defer.assert_awaited_once_with()

    async def test_pagination_uses_fresh_votes_and_clamps_the_last_page(self):
        row,message=await self.photo()
        for uid in range(100,127):self.system.store.vote(row['id'],uid,now=BASE+1)
        i,panel=await self.panel(row,message)
        self.assertIn('@jugador100',self.response(i).kwargs['embed'].description)
        self.assertNotIn('@jugador125',self.response(i).kwargs['embed'].description)
        click=self.interaction(SimpleNamespace(id=999999))
        await panel.next.callback(click)
        result=click.edit_original_response.call_args
        self.assertIn('@jugador125',result.kwargs['embed'].description);self.assertNotIn('@jugador100',result.kwargs['embed'].description)
        self.assertTrue(panel.next.disabled);self.assertFalse(panel.previous.disabled)
        self.assertIn('Página 2/2',result.kwargs['embed'].footer.text)
        for uid in (125,126):self.system.store.vote(row['id'],uid,False,now=BASE+2)
        await panel.refresh.callback(click)
        self.assertEqual(panel.page,0);self.assertTrue(panel.previous.disabled);self.assertTrue(panel.next.disabled)
        self.assertIn('**25 votos**',click.edit_original_response.call_args.kwargs['embed'].description)

    async def test_panel_is_actor_bound_and_rechecks_channel_access_on_every_page(self):
        row,message=await self.photo();i,panel=await self.panel(row,message)
        outsider=self.interaction(message,user=3)
        self.assertFalse(await panel.interaction_check(outsider));self.assertTrue(self.response(outsider).kwargs['ephemeral'])
        self.channel.permissions_for=lambda user:discord.Permissions(view_channel=False)
        click=self.interaction(SimpleNamespace(id=999999))
        with self.assertRaisesRegex(ValueError,'No tienes acceso'):await panel.refresh.callback(click)
        click.edit_original_response.assert_not_awaited()

    async def test_wrong_guild_channel_bot_and_forged_photo_controls_cannot_read_votes(self):
        row,message=await self.photo()
        for field,value in (('guild_id',GUILD+1),('channel_id',FOTOS_CHANNEL+1)):
            i=self.interaction(message);setattr(i,field,value)
            with self.assertRaises(ValueError):await self.system.show_voters(i,row['id'])
            i.response.send_message.assert_not_awaited()
        i=self.interaction(message);i.user.bot=True
        with self.assertRaises(ValueError):await self.system.show_voters(i,row['id'])
        i=self.interaction(SimpleNamespace(id=123))
        with self.assertRaisesRegex(ValueError,'no está disponible'):await self.system.show_voters(i,row['id'])

    async def test_missing_withdrawn_or_foreign_photo_cannot_be_read_from_an_old_panel(self):
        row,message=await self.photo();i,panel=await self.panel(row,message)
        message.author.id=123
        with self.assertRaisesRegex(ValueError,'no pertenece'):await panel.refresh.callback(i)
        message.author.id=self.bot.user.id;self.messages.pop(message.id)
        with self.assertRaisesRegex(ValueError,'publicación'):await panel.refresh.callback(i)
        self.messages[message.id]=message;self.system.store.deleted(row['source'])
        with self.assertRaisesRegex(ValueError,'no está disponible'):await panel.refresh.callback(i)

    async def test_author_can_read_closed_week_results_while_voting_buttons_remain_disabled(self):
        row,message=await self.photo();self.system.store.vote(row['id'],3,now=BASE+1)
        week=self.system.store.current(BASE);self.system.store.freeze(week['week'],week['ends'])
        i,panel=await self.panel(row,message,user=1)
        self.assertIn('@jugador3',self.response(i).kwargs['embed'].description)
        controls=PhotoControls(row['id'],1,True)
        states={child.custom_id:child.item.disabled for child in controls.children}
        self.assertTrue(states[f"lv:photo:{row['id']}:vote"]);self.assertTrue(states[f"lv:photo:{row['id']}:remove"])
        self.assertFalse(states[f"lv:photo:{row['id']}:voters"])

    async def test_member_who_left_the_guild_is_kept_in_the_vote_count_and_list(self):
        row,message=await self.photo();self.system.store.vote(row['id'],987654321,now=BASE+1)
        async def member(uid):
            if uid==987654321:raise discord.NotFound(SimpleNamespace(status=404,reason='missing'),'missing')
            return self.named_user(uid)
        self.guild.fetch_member.side_effect=member
        self.bot.fetch_user.return_value=self.named_user(987654321,'cuentafuera','Persona que salió')
        self.bot.fetch_user.side_effect=None
        i,panel=await self.panel(row,message)
        text=self.response(i).kwargs['embed'].description
        self.assertIn('Persona que salió',text);self.assertIn('@cuentafuera',text)
        self.assertNotIn('<@',text);self.assertIn('**1 voto**',text)
        self.bot.fetch_user.assert_awaited_once_with(987654321)
        self.assertEqual(self.system.store.voters(row['id'])['users'],[987654321])

    async def test_reported_id_is_rendered_as_complete_visible_name_and_username(self):
        row,message=await self.photo();uid=709959717299945552
        self.system.store.vote(row['id'],uid,now=BASE+1)
        named=self.named_user(uid,'forkypr24','😈 Keyler Santos 🖤🔥')
        self.system.member_directory.load.return_value=[self.named_user(1),named]
        i,panel=await self.panel(row,message)
        text=self.response(i).kwargs['embed'].description
        self.assertIn('**😈 Keyler Santos 🖤🔥** · @forkypr24',text)
        self.assertIn('Foto de **Jugador 1** · @jugador1',text)
        self.assertNotIn(str(uid),text);self.assertNotIn('<@',text)
        self.guild.fetch_member.assert_not_awaited();self.bot.fetch_user.assert_not_awaited()

    async def test_unavailable_member_directory_uses_exact_member_lookups(self):
        row,message=await self.photo();self.system.store.vote(row['id'],3,now=BASE+1)
        self.system.member_directory.load.side_effect=DirectoryUnavailable()
        i,panel=await self.panel(row,message)
        self.assertIn('Jugador 3',self.response(i).kwargs['embed'].description)
        self.guild.fetch_member.assert_any_await(3);self.bot.fetch_user.assert_not_awaited()

    async def test_deleted_account_has_an_explicit_label_without_losing_its_vote(self):
        row,message=await self.photo();self.system.store.vote(row['id'],3,now=BASE+1)
        async def member(uid):
            if uid==3:raise discord.NotFound(SimpleNamespace(status=404,reason='missing'),'missing')
            return self.named_user(uid)
        self.guild.fetch_member.side_effect=member
        self.bot.fetch_user.side_effect=discord.NotFound(SimpleNamespace(status=404,reason='missing'),'missing')
        i,panel=await self.panel(row,message)
        text=self.response(i).kwargs['embed'].description
        self.assertIn('Cuenta eliminada o no disponible',text);self.assertIn('**1 voto**',text)
        self.assertNotIn('<@',text);self.assertEqual(self.system.store.voters(row['id'])['users'],[3])

    async def test_temporary_name_failure_can_be_refreshed_without_mislabeling_the_account(self):
        row,message=await self.photo();self.system.store.vote(row['id'],3,now=BASE+1)
        async def member(uid):
            if uid==3:raise discord.HTTPException(SimpleNamespace(status=503,reason='unavailable'),'temporary')
            return self.named_user(uid)
        self.guild.fetch_member.side_effect=member
        i,panel=await self.panel(row,message)
        text=self.response(i).kwargs['embed'].description
        self.assertIn('Nombre no disponible temporalmente',text);self.assertNotIn('Cuenta eliminada',text)
        self.guild.fetch_member.side_effect=lambda uid:self.named_user(uid)
        click=self.interaction(SimpleNamespace(id=999999));await panel.refresh.callback(click)
        self.assertIn('@jugador3',click.edit_original_response.call_args.kwargs['embed'].description)
        self.assertNotIn('no disponible',click.edit_original_response.call_args.kwargs['embed'].description)
        self.assertEqual(self.system.store.entry(row['id'])['votes'],1)

    async def test_full_length_names_fit_and_user_markdown_or_mentions_are_not_interpreted(self):
        row,message=await self.photo()
        for uid in range(100,125):self.system.store.vote(row['id'],uid,now=BASE+1)
        nickname='*'*32;username='_'*32
        self.system.member_directory.load.return_value=[self.named_user(uid,username,nickname) for uid in range(100,125)]
        i,panel=await self.panel(row,message)
        text=self.response(i).kwargs['embed'].description
        escaped=discord.utils.escape_markdown(nickname)
        self.assertEqual(text.count(f'**{escaped}**'),25);self.assertLessEqual(len(text),4096)
        self.assertNotIn('<@',text)
        self.system.member_directory.load.return_value=[self.named_user(uid,'jugador','@everyone <@123456789012345678>') for uid in range(100,125)]
        click=self.interaction(SimpleNamespace(id=999999));await panel.refresh.callback(click)
        text=click.edit_original_response.call_args.kwargs['embed'].description
        self.assertNotIn('@everyone',text);self.assertNotIn('<@123456789012345678>',text)

    async def test_read_failure_is_private_and_does_not_turn_the_query_into_a_vote(self):
        row,message=await self.photo();self.system.store.vote(row['id'],2,now=BASE+1)
        i=self.interaction(message);i.client.photos=self.system
        with patch.object(self.system.store,'voters',side_effect=OSError('private detail')):
            await PhotoButton(row['id'],'voters').callback(i)
        response=self.response(i)
        self.assertTrue(response.kwargs['ephemeral']);self.assertNotIn('private detail',response.args[0])
        self.assertEqual(self.system.store.voters(row['id'])['users'],[2])

    async def test_persistent_voter_button_roundtrips_through_the_dynamic_dispatcher(self):
        button=PhotoButton(123,'voters',0,True)
        match=PhotoButton.__discord_ui_compiled_template__.fullmatch(button.custom_id)
        restored=await PhotoButton.from_custom_id(None,None,match)
        self.assertEqual(restored.action,'voters');self.assertEqual(restored.custom_id,button.custom_id)
        self.assertEqual(restored.item.label,'Ver votantes');self.assertFalse(restored.item.disabled)

    async def test_existing_current_and_closed_cards_get_the_button_without_editing_their_photos(self):
        row,message=await self.photo();self.system.store.vote(row['id'],2,now=BASE+1)
        week=self.system.store.current(BASE);self.system.store.freeze(week['week'],week['ends'])
        controls=PhotoControls(row['id'],1,True)
        for child in list(controls.children):
            if child.custom_id.endswith(':voters'):controls.remove_item(child)
        self.decorate(message,dict(view=controls));before=self.system.store.entry(row['id'])
        content=message.content;image=message.embeds[0].image.url;files=list(message.attachments)
        message.edit.reset_mock();self.tracked.clear()
        await self.system.upgrade_voter_controls(self.channel)
        self.assertTrue(self.tracked)
        old_ids=[child['custom_id'] for group in self.tracked[0]['components'] for child in group['components']]
        self.assertNotIn(f"lv:photo:{row['id']}:voters",old_ids)
        args=message.edit.call_args.kwargs
        self.assertNotIn('embed',args);self.assertNotIn('content',args);self.assertNotIn('attachments',args)
        self.assertFalse(next(child.item.disabled for child in args['view'].children if child.custom_id.endswith(':voters')))
        self.assertEqual(message.content,content);self.assertEqual(message.embeds[0].image.url,image)
        self.assertEqual(message.attachments,files);self.assertEqual(self.system.store.entry(row['id']),before)
        await self.system.upgrade_voter_controls(self.channel)
        message.edit.assert_awaited_once()
