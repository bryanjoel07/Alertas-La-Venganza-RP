"""Exercise the actual SDK response types against a single-message Discord transport."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord
from discord.webhook.async_ import async_context

from settings_app import AppView
from settings_panel import ConfirmSettings,ReloadView,RewardScope
import test_bot_settings as fixtures
import test_settings_center as center_fixtures


class SinglePanelTests(fixtures.SettingsFixtures,unittest.IsolatedAsyncioTestCase):
    tracked=fixtures.SettingsUITests.tracked
    interaction=fixtures.SettingsUITests.interaction
    fill=center_fixtures.CenterTests.fill
    install_modules=center_fixtures.CenterTests.install_modules

    async def asyncSetUp(self):
        await fixtures.SettingsUITests.asyncSetUp(self)
        self.message=SimpleNamespace(id=90001)
        self.created=0;self.callbacks=[];self.edits=[];self.modals=[];self.views=[];self.current=None
        self.adapter=SimpleNamespace(create_interaction_response=AsyncMock(side_effect=self.respond))
        token=async_context.set(self.adapter)
        self.addCleanup(async_context.reset,token)
        self.addCleanup(self.stop_views)

    def stop_views(self):
        for view in (*self.views,*self.modals):view.stop()

    async def respond(self,interaction_id,token,**kwargs):
        payload=kwargs['params'].payload
        self.callbacks.append(payload)
        if payload['type']==5:
            self.assertEqual(self.created,0,'A second deferred channel response would create another panel')
            self.assertEqual(payload['data']['flags'],64)
            self.created+=1
        else:
            self.assertEqual(self.created,1)
            self.assertIn(payload['type'],(6,9),'Only update the message or open its modal')
        return {'interaction':{'id':str(interaction_id),'response_message_id':str(self.message.id)}}

    def click(self,kind=discord.InteractionType.component):
        i=self.interaction();i.type=kind;i.id=1000+len(self.callbacks);i.token='test-token';i._session=None
        i.message=None if kind is discord.InteractionType.application_command else self.message
        i._state=SimpleNamespace(http=SimpleNamespace(proxy=None,proxy_auth=None),store_view=self.modals.append)
        i.response=discord.InteractionResponse(i)
        async def edit(**kwargs):
            self.assertEqual(i.response.type,discord.InteractionResponseType.deferred_channel_message if i.type is discord.InteractionType.application_command else
                discord.InteractionResponseType.deferred_message_update)
            self.assertEqual(self.created,1)
            if i.message is not None:self.assertEqual(i.message.id,self.message.id)
            self.assertIsNone(kwargs.get('content'))
            self.assertFalse(kwargs.get('embeds'))
            view=kwargs['view'];self.assertIsInstance(view,discord.ui.LayoutView)
            self.assertLessEqual(view.content_length(),4000)
            self.assertLessEqual(len(list(view.walk_children())),40)
            self.assertTrue(all(c['type']==17 for c in view.to_components()))
            self.edits.append((self.message.id,view.to_components()));self.views.append(view);self.current=view
            return self.message
        i.edit_original_response=AsyncMock(side_effect=edit)
        async def unexpected(*args,**kwargs):self.fail('The settings flow sent another message')
        i.followup.send=AsyncMock(side_effect=unexpected)
        return i

    async def open(self,section='home'):
        await self.system.group.get_command('panel').callback(self.click(discord.InteractionType.application_command))
        if section!='home':await self.current.move(self.click(),section)
        return self.current

    def button(self,label):
        return next(c for c in self.current.walk_children() if isinstance(c,discord.ui.Button) and c.label==label)

    async def submit(self,modal):
        await modal.on_submit(self.click(discord.InteractionType.modal_submit))
        return self.current

    def assert_single(self):
        self.assertEqual(self.created,1)
        self.assertEqual({mid for mid,_ in self.edits},{self.message.id})
        self.assertEqual(sum(p['type']==5 for p in self.callbacks),1)

    async def test_repeated_server_edits_preview_and_save_update_the_original_message(self):
        original=await self.open('server')
        for hour in ('20:30','21:15'):
            await self.button('Hora del Server Up').callback(self.click())
            form=self.modals[-1];form.fields[0]._value=hour
            before=self.store.snapshot(fixtures.BASE)['values']['daily_server_up_time']
            confirm=await self.submit(form)
            self.assertIsInstance(confirm,ConfirmSettings)
            self.assertEqual(self.store.snapshot(fixtures.BASE)['values']['daily_server_up_time'],before)
            await confirm.save.callback(self.click())
            self.assertIsInstance(self.current,AppView)
            self.assertIn(hour,str(self.current.to_components()))
            self.assertEqual(self.store.snapshot(fixtures.BASE)['values']['daily_server_up_time'],hour)
            self.assertTrue(confirm.retired)
        self.assertTrue(original.retired);self.assert_single()
        self.assertEqual(len(self.store.history()),2)

    async def test_system_form_cancel_and_invalid_input_keep_one_message_and_no_mutation(self):
        await self.open('server')
        await self.button('Avisos y menciones').callback(self.click());form=self.modals[-1]
        self.fill(form,dict(daily_enabled=False,everyone=False),self.click(discord.InteractionType.modal_submit))
        confirm=await self.submit(form);await confirm.cancel.callback(self.click())
        self.assertIsInstance(self.current,AppView)
        self.assertIn('Cancelado',str(self.current.to_components()))
        self.assertTrue(self.store.snapshot(fixtures.BASE)['systems']['announcements']['everyone'])
        await self.button('Hora del Server Up').callback(self.click());form=self.modals[-1];form.fields[0]._value='25:99'
        await self.submit(form);self.assertIsInstance(self.current,ReloadView)
        await self.current.reload.callback(self.click());self.assertIsInstance(self.current,AppView)
        self.assertEqual(self.store.snapshot(fixtures.BASE)['revision'],0);self.assert_single()

    async def test_photo_scope_and_rewards_remain_in_the_original_message(self):
        await self.open('photos')
        await self.button('Cambiar premios del podio').callback(self.click());scope=self.current
        self.assertIsInstance(scope,RewardScope)
        await scope.next_week.callback(self.click());form=self.modals[-1]
        for field,value in zip(form.fields,('800','500','250')):field._value=value
        confirm=await self.submit(form);self.assertTrue(scope.retired)
        await confirm.save.callback(self.click())
        self.assertEqual(self.store.snapshot(fixtures.BASE)['next_rewards'],[800,500,250])
        self.assertEqual(self.current.section,'photos');self.assert_single()

    async def test_search_and_history_restoration_reuse_the_message(self):
        await self.open()
        await self.button('Buscar una función').callback(self.click());form=self.modals[-1];form.term._value='ajustes'
        await self.submit(form);self.assertEqual(self.current.section,'directory')
        self.assertIn('ajustes panel',str(self.current.to_components()))
        self.store.apply('schedule','20:30',0,1,'earlier',now=fixtures.BASE)
        await self.current.move(self.click(),'detail',detail='earlier')
        await self.button('Revisar restauración').callback(self.click())
        self.assertIsInstance(self.current,ConfirmSettings)
        self.assertEqual(self.store.snapshot(fixtures.BASE)['values']['daily_server_up_time'],'20:30')
        await self.current.save.callback(self.click())
        self.assertEqual(self.store.snapshot(fixtures.BASE)['values']['daily_server_up_time'],'18:30')
        self.assert_single()

    async def test_catalog_editor_updates_price_in_place_and_preserves_balance(self):
        await self.install_modules();await self.open('economy')
        await self.button('Editar productos').callback(self.click())
        select=next(c for c in self.current.walk_children() if isinstance(c,discord.ui.Select) and c.placeholder=='Elige el producto')
        select._values=['test-banner'];await select.callback(self.click());form=self.modals[-1]
        self.fill(form,dict(price=600,active=True),self.click(discord.InteractionType.modal_submit))
        confirm=await self.submit(form);await confirm.save.callback(self.click())
        self.assertEqual(self.store.catalog()[0]['price'],600)
        with self.store.db(readonly=True) as db:
            self.assertEqual(db.execute('SELECT balance FROM eco_accounts WHERE user_id=1').fetchone()[0],10000)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_ledger').fetchone()[0],0)
        self.assert_single()

    async def test_large_preview_paginates_without_losing_text_or_sending_messages(self):
        old='antes '+('a'*1790);new='después '+('b'*1790)
        state=self.store.snapshot(fixtures.BASE)
        self.store.apply('system',state['systems']['guide']|dict(intro=old),0,1,'old',target='guide',now=fixtures.BASE)
        await self.open('rules');await self.button('Presentación de la guía').callback(self.click());form=self.modals[-1]
        self.fill(form,self.store.snapshot(fixtures.BASE)['systems']['guide']|dict(intro=new),self.click(discord.InteractionType.modal_submit))
        confirm=await self.submit(form);self.assertGreater(len(confirm.pages),1)
        for value in (old,new):
            for start in range(0,len(value),1000):self.assertIn(value[start:start+1000],'\n'.join(confirm.pages))
        while not confirm.next.disabled:await confirm.next.callback(self.click())
        while not confirm.prev.disabled:await confirm.prev.callback(self.click())
        await confirm.cancel.callback(self.click())
        self.assertEqual(self.store.snapshot(fixtures.BASE)['systems']['guide']['intro'],old)
        self.assert_single()

    async def test_retired_view_timeouts_cannot_replace_the_current_screen(self):
        old=await self.open('server')
        await self.button('Hora del Server Up').callback(self.click());form=self.modals[-1];form.fields[0]._value='20:00'
        confirm=await self.submit(form)
        edits=len(self.edits);await old.on_timeout();self.assertEqual(len(self.edits),edits)
        await confirm.cancel.callback(self.click());edits=len(self.edits)
        await confirm.on_timeout();self.assertEqual(len(self.edits),edits)
        self.assertIsInstance(self.current,AppView);self.assert_single()

    async def test_losing_administrator_permission_updates_the_same_panel_without_saving(self):
        await self.open('server')
        await self.button('Hora del Server Up').callback(self.click());form=self.modals[-1];form.fields[0]._value='20:00'
        confirm=await self.submit(form)
        self.guild.fetch_member.return_value=SimpleNamespace(id=1,guild_permissions=discord.Permissions.none())
        await confirm.save.callback(self.click())
        self.assertIsInstance(self.current,ReloadView)
        self.assertIn('administradores',str(self.current.to_components()))
        self.assertEqual(self.store.snapshot(fixtures.BASE)['revision'],0);self.assert_single()
