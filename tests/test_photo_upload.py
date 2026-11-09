from datetime import datetime,timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

import discord
from photos import PhotoControls,PhotoButton,UploadButton,UploadForm,PhotoUploadPanel,FOTOS_CHANNEL
from test_photos import PhotoServiceFixtures,BASE,GUILD


class PhotoUploadTests(PhotoServiceFixtures,unittest.IsolatedAsyncioTestCase):
    async def upload(self,owner=1):
        source=self.source(owner=owner)
        i=self.interaction(None,user=owner)
        await self.system.submit_upload(i,source.attachments[0],'Mi foto')
        row=next(r for r in self.system.store.entries() if r['upload_key']==f'{i.id}:{source.attachments[0].id}')
        return row,self.messages[row['control']],i,source

    def legacy(self):
        source=self.source()
        image=source.attachments[0]
        entry=self.system.store.register(source.id,image.id,1,image.filename,image.url,BASE,BASE)
        control=self.message(99);control.reference=SimpleNamespace(message_id=source.id)
        self.decorate(control,{'embed':self.system.control_embed(self.system.store.entry(entry)),'view':PhotoControls(entry)})
        self.system.store.control(entry,control.id)
        return source,control,entry

    async def test_upload_places_image_credit_and_persistent_votes_in_one_standalone_message(self):
        row,message,_,source=await self.upload()
        self.assertEqual(self.channel.send.await_count,1)
        self.assertIsNone(message.reference);self.assertEqual(len(message.attachments),1)
        self.assertTrue(message.embeds[0].image.url)
        self.assertIn('<@1>',message.embeds[0].description);self.assertIn('Mi foto',message.embeds[0].description)
        self.assertEqual(row['source'],message.id);self.assertEqual(row['control'],message.id)
        self.assertEqual(row['post_mode'],'post');self.assertIsNone(row['media'])
        self.assertEqual([c.custom_id for r in message.components for c in r.children],
            [f"lv:photo:{row['id']}:vote",f"lv:photo:{row['id']}:remove",'lv:photo:upload'])
        source.reply.assert_not_awaited();source.edit.assert_not_awaited();source.delete.assert_not_awaited()
        self.assertTrue(PhotoControls(row['id']).is_persistent());self.assertTrue(PhotoUploadPanel().is_persistent())
        for child in PhotoControls(row['id']).children:
            cls=UploadButton if child.custom_id=='lv:photo:upload' else PhotoButton
            match=cls.__discord_ui_compiled_template__.fullmatch(child.custom_id)
            restored=await cls.from_custom_id(None,None,match)
            self.assertEqual(restored.custom_id,child.custom_id)

    async def test_open_upload_and_modal_file_payload_revalidate_channel_permissions(self):
        i=self.interaction(None,user=1)
        await self.system.open_upload(i)
        form=i.response.send_modal.call_args.args[0]
        payload=form.to_dict()['components']
        self.assertEqual(payload[0]['component']['type'],19)
        self.assertEqual(payload[0]['component']['max_values'],1)
        self.assertFalse(payload[1]['component']['required'])
        form.photo._values=[self.source().attachments[0]];form.caption._value='Desde la ciudad'
        i.channel_id=123
        await form.on_submit(i)
        self.assertFalse(self.system.store.entries())
        i.channel_id=FOTOS_CHANNEL
        self.channel.permissions_for=lambda user:discord.Permissions(view_channel=True,send_messages=False)
        with self.assertRaises(ValueError):await self.system.submit_upload(i,form.photo.values[0])
        self.assertFalse(self.system.store.entries())

    async def test_modal_submission_publishes_once_and_duplicate_delivery_reuses_the_photo(self):
        form=UploadForm(self.system);form.photo._values=[self.source().attachments[0]];form.caption._value='Buenas'
        i=self.interaction(None,user=1)
        await form.on_submit(i);await form.on_submit(i)
        self.assertEqual(len(self.system.store.entries()),1);self.assertEqual(self.channel.send.await_count,1)

    async def test_votes_validate_the_bot_photo_while_storing_human_owner_credit(self):
        row,message,_,_=await self.upload()
        i=self.interaction(message,user=2)
        await self.system.vote(i,row['id'],True);await self.system.vote(i,row['id'],True)
        self.assertEqual(self.system.store.entry(row['id'])['votes'],1)
        await self.system.vote(i,row['id'],False)
        self.assertEqual(self.system.store.entry(row['id'])['votes'],0)
        i.user.id=1
        with self.assertRaisesRegex(ValueError,'propia'):await self.system.vote(i,row['id'],True)
        i.user.id=2;i.channel_id=123
        with self.assertRaises(ValueError):await self.system.vote(i,row['id'],True)

    async def test_native_uploads_do_not_generate_replies_or_duplicate_photo_posts(self):
        direct=self.source()
        await self.system.observe(direct);await self.system.scan(self.channel)
        self.assertFalse(self.system.store.entries())
        direct.reply.assert_not_awaited();self.channel.send.assert_not_awaited()
        direct.edit.assert_not_awaited();direct.delete.assert_not_awaited()

    async def test_legacy_reply_is_replaced_only_after_the_full_photo_is_confirmed_and_votes_survive(self):
        source,old,entry=self.legacy();self.system.store.vote(entry,2,now=BASE)
        old_votes=self.system.store.entry(entry)['votes']
        async with self.system.lock:
            await self.system.ensure_control(self.system.store.entry(entry),source)
        row=self.system.store.entry(entry);message=self.messages[row['control']]
        self.assertNotEqual(message.id,old.id);self.assertIsNone(message.reference)
        self.assertEqual(row['votes'],old_votes);self.assertEqual(row['source'],source.id)
        self.assertTrue(message.embeds[0].image.url);old.delete.assert_awaited_once()
        source.delete.assert_not_awaited();source.edit.assert_not_awaited();self.assertIn(source.id,self.messages)
        self.assertIsNone(row['retired_control']);self.assertTrue(self.tracked)

    async def test_failed_legacy_republication_keeps_the_original_reply_and_votes_for_retry(self):
        source,old,entry=self.legacy();self.system.store.vote(entry,2,now=BASE)
        self.channel.send.side_effect=discord.HTTPException(SimpleNamespace(status=503,reason='Unavailable'),'later')
        with self.assertRaises(discord.HTTPException):await self.system.ensure_control(self.system.store.entry(entry),source)
        old.delete.assert_not_awaited();source.delete.assert_not_awaited()
        self.assertEqual(self.system.store.entry(entry)['votes'],1)
        self.channel.send.side_effect=self.send
        await self.system.ensure_post(self.system.store.entry(entry),self.channel)
        old.delete.assert_awaited_once();self.assertEqual(self.system.store.entry(entry)['votes'],1)

    async def test_send_success_followed_by_restart_reconciles_the_post_without_publishing_twice(self):
        attachment=self.source().attachments[0];i=self.interaction(None,user=1)
        with patch.object(self.system.store,'posted',side_effect=RuntimeError('restart')):
            with self.assertRaises(RuntimeError):await self.system.submit_upload(i,attachment)
        self.assertEqual(self.channel.send.await_count,1)
        row=self.system.store.entries()[0];self.assertEqual(row['post_mode'],'pending');self.assertTrue(row['media'])
        await self.system.ensure_post(row,self.channel)
        self.assertEqual(self.channel.send.await_count,1);self.assertEqual(self.system.store.entry(row['id'])['post_mode'],'post')

    async def test_deleting_a_published_photo_withdraws_it_and_does_not_repost_it(self):
        row,message,_,_=await self.upload()
        await message.delete()
        await self.system.deleted(GUILD,FOTOS_CHANNEL,[message.id])
        await self.system.refresh_controls(self.channel)
        current=self.system.store.entry(row['id'])
        self.assertFalse(current['active']);self.assertEqual(current['rendered_closed'],1)
        self.assertEqual(self.channel.send.await_count,1)

    async def test_withdraw_requires_the_owner_or_moderation_and_confirmation(self):
        row,message,_,_=await self.upload()
        command=self.system.group.get_command('retirar');outsider=self.interaction(None,user=2)
        with self.assertRaises(ValueError):await command.callback(outsider,row['id'])
        message.delete.assert_not_awaited()
        owner=self.interaction(None,user=1);await command.callback(owner,row['id'])
        confirm=owner.response.send_message.call_args.kwargs['view'];message.delete.assert_not_awaited()
        await confirm.action(owner)
        message.delete.assert_awaited_once();self.assertFalse(self.system.store.entry(row['id'])['active'])

    async def test_ready_migrates_the_current_photo_and_verifies_upload_control_and_registered_commands(self):
        source,old,entry=self.legacy()
        self.bot.tree.fetch_commands=AsyncMock(return_value=[SimpleNamespace(name='foto',to_dict=lambda:{'options':[{'name':n} for n in ('semana','premio','subir','retirar')]})])
        await self.system.ready()
        self.assertTrue(self.system.prepared);self.assertEqual(self.system.store.entry(entry)['post_mode'],'post')
        old.delete.assert_awaited_once();source.delete.assert_not_awaited()
        panel=self.messages[int(self.system.store.config('panel'))]
        self.assertFalse(panel.pinned)
        self.assertEqual([c.custom_id for r in panel.components for c in r.children],['lv:photo:upload'])
        count=self.channel.send.await_count;await self.system.ready();self.assertEqual(self.channel.send.await_count,count)

    async def test_only_closed_week_winner_is_pinned_and_original_panel_pin_is_removed(self):
        week=self.system.store.current(BASE);panel=self.message(99);panel.embeds=[self.system.panel_embed(week)];panel.pinned=True
        self.system.store.config('panel',panel.id);await self.system.panel(self.channel)
        panel.unpin.assert_awaited_once();self.assertFalse(panel.pinned)
        row,message,_,_=await self.upload()
        with self.assertRaisesRegex(ValueError,'cierre semanal'):await self.system.pin(message)
        self.system.store.vote(row['id'],2,now=BASE+100)
        with patch('photos.time.time',return_value=week['ends']+1):await self.system.settle(self.channel,week)
        result=self.system.store.week(week['week']);winner=self.messages[result['announcement']]
        self.assertTrue(winner.pinned);self.assertEqual(result['winning_votes'],1);self.assertIn('<@1>',winner.embeds[0].description)
        self.assertFalse(self.system.store.due(week['ends']+1))

    async def test_weekly_publication_is_reconciled_if_the_database_write_is_interrupted(self):
        row,_,_,_=await self.upload();self.system.store.vote(row['id'],2,now=BASE+10)
        week=self.system.store.current(BASE)
        with patch('photos.time.time',return_value=week['ends']+1),patch.object(self.system.store,'published',side_effect=RuntimeError('restart')):
            with self.assertRaises(RuntimeError):await self.system.settle(self.channel,week)
        count=self.channel.send.await_count
        with patch('photos.time.time',return_value=week['ends']+10):await self.system.settle(self.channel,self.system.store.week(week['week']))
        self.assertEqual(self.channel.send.await_count,count)

    async def test_non_images_oversize_and_wrong_channel_do_not_create_pending_posts(self):
        attachment=self.source().attachments[0];i=self.interaction(None,user=1)
        attachment.filename='file.txt';attachment.content_type='text/plain'
        with self.assertRaises(ValueError):await self.system.submit_upload(i,attachment)
        attachment.filename='foto.png';attachment.content_type='image/png';attachment.size=self.guild.filesize_limit+1
        with self.assertRaises(ValueError):await self.system.submit_upload(i,attachment)
        self.assertFalse(self.system.store.entries());self.channel.send.assert_not_awaited()

    async def test_prize_confirmation_rechecks_economy_authorization(self):
        i=self.interaction(None);self.bot.economy.authorized.side_effect=ValueError('Solo administradores')
        command=self.system.group.get_command('premio')
        with self.assertRaises(ValueError):await command.callback(i,'ninguno')
        self.bot.economy.authorized.side_effect=None;await command.callback(i,'ninguno')
        confirm=i.response.send_message.call_args.kwargs['view']
        self.bot.economy.authorized.side_effect=ValueError('Solo administradores')
        with self.assertRaises(ValueError):await confirm.action(i)
        self.assertIsNone(self.system.store.current(BASE)['prize_actor'])
