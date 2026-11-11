import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock,patch

import discord

from bot_settings import SettingsStore
from bug_store import BugStore
from economy_store import SCHEMA
from feedback_store import FeedbackStore
from minigame_store import MinigameStore
from recruitment_store import RecruitmentStore
from settings_app import AppView,SystemForm
from settings_catalog import BY_FORM,SECTIONS,read_form,validate
from settings_panel import ConfirmSettings
from suggestion_store import SuggestionStore
from tickets_store import TicketStore
import test_bot_settings as fixtures


class CenterTests(fixtures.SettingsFixtures,unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.SettingsUITests.asyncSetUp
    tracked=fixtures.SettingsUITests.tracked
    interaction=fixtures.SettingsUITests.interaction

    async def install_modules(self):
        self.tickets=TicketStore(self.path);self.tickets.initialize()
        self.bugs=BugStore(self.path);self.bugs.initialize()
        self.feedback=FeedbackStore(self.path);self.feedback.initialize()
        self.suggestions=SuggestionStore(self.path);self.suggestions.initialize()
        self.recruitment=RecruitmentStore(self.path);self.recruitment.initialize()
        with self.store.db() as db:
            for sql in SCHEMA.split(';'):
                if sql.strip():db.execute(sql)
            db.execute("INSERT INTO eco_products(sku,name,kind,tier,price,payload) VALUES ('test-banner','Mi banner','banner','profile',900,'{}')")
            db.execute('INSERT INTO eco_accounts VALUES (1,10000)')

    def fill(self,modal,values,i):
        components=[]
        for field in modal.spec.fields:
            control=modal.controls[field.key];value=values[field.key]
            data={'custom_id':control.custom_id}
            if field.kind=='bool':data.update(type=3,values=['1' if value else '0'])
            elif field.kind=='multi':data.update(type=3,values=[str(n) for n in value])
            else:data.update(type=4,value=str(value))
            components.append(dict(type=18,component=data))
        modal._refresh(i,components,{})

    async def preview(self,key,values,product=None):
        modal=SystemForm(self.system,1,self.store.snapshot(fixtures.BASE),key,product=product)
        i=self.interaction();self.fill(modal,values,i);await modal.on_submit(i)
        self.assertFalse(i.response.defer.call_args.kwargs.get('thinking',False))
        self.assertIsInstance(i.edit_original_response.call_args.kwargs['view'],ConfirmSettings)
        return i.edit_original_response.call_args.kwargs['view']

    async def test_all_sixteen_sections_use_native_layout_and_all_forms_serialize(self):
        before=self.path.read_bytes()
        for section in ('home',*(s.key for s in SECTIONS)):
            with self.subTest(section=section):
                i=self.interaction();await self.system.open(i,section)
                view=i.edit_original_response.call_args.kwargs['view']
                self.assertIsInstance(view,AppView)
                self.assertEqual(view.to_components()[0]['type'],17)
                self.assertLessEqual(len(list(view.walk_children())),40)
                menus=[c for c in view.walk_children() if isinstance(c,discord.ui.Select) and len(c.options)==16]
                self.assertEqual(len(menus),1)
                self.assertEqual(i.edit_original_response.call_args.kwargs['embeds'],[])
                view.stop()
        for key,spec in BY_FORM.items():
            payload=SystemForm(self.system,1,self.store.snapshot(fixtures.BASE),key).to_dict()
            self.assertEqual(len(payload['components']),len(spec.fields))
            self.assertLessEqual(len(payload['components']),5)
        self.assertEqual(self.path.read_bytes(),before)
        self.bot.changes.tracked.assert_not_awaited()

    async def test_real_modal_payload_previews_then_applies_ticket_settings_with_history(self):
        await self.install_modules()
        values=dict(max_open=2,remind_hours=4,escalate_hours=12,inactive_hours=48,close_warning_hours=6)
        view=await self.preview('ticket_attention',values)
        self.assertEqual(self.tickets.config('max_open'),'3')
        await view.save.callback(self.interaction())
        self.assertEqual(self.tickets.config('max_open'),'2')
        self.assertEqual(self.tickets.config('escalate_hours'),'12')
        self.assertEqual(self.store.history()[0]['target'],'ticket_attention')
        self.assertEqual(self.store.history()[0]['sync_state'],'done')
        self.assertEqual(self.store.snapshot(fixtures.BASE)['revision'],1)
        self.assertEqual(self.snapshots[0]['settings']['systems']['ticket_attention']['max_open'],3)

    async def test_lost_admin_rights_block_new_native_forms_and_confirmation(self):
        await self.install_modules()
        values=self.store.snapshot(fixtures.BASE)['systems']['suggestions']|dict(accepting=False)
        view=await self.preview('suggestions',values)
        self.guild.fetch_member.return_value=SimpleNamespace(id=1,guild_permissions=discord.Permissions.none())
        await view.save.callback(self.interaction())
        self.assertEqual(self.store.snapshot(fixtures.BASE)['revision'],0)
        self.bot.changes.tracked.assert_not_awaited()
        citizen=self.interaction(SimpleNamespace(id=2,guild_permissions=discord.Permissions.none()))
        app=AppView(self.system,1,self.interaction(),self.store.snapshot(fixtures.BASE))
        self.assertFalse(await app.interaction_check(citizen));app.stop()

    async def test_outside_command_changes_are_checked_even_if_global_revision_did_not_change(self):
        await self.install_modules()
        values=self.store.snapshot(fixtures.BASE)['systems']['ticket_attention']|dict(max_open=2)
        view=await self.preview('ticket_attention',values)
        self.tickets.config('max_open',4)
        await view.save.callback(self.interaction())
        self.assertEqual(self.tickets.config('max_open'),'4')
        self.assertIsNone(self.store.receipt(view.draft.token))

    async def test_product_form_changes_future_price_and_never_touches_balances(self):
        await self.install_modules()
        product=self.store.catalog()[0]
        view=await self.preview('product',dict(price='1,500',active=False),product)
        self.assertEqual(self.store.catalog()[0]['price'],900)
        await view.save.callback(self.interaction())
        row=self.store.catalog()[0]
        self.assertEqual(row['price'],1500);self.assertFalse(row['active']);self.assertEqual(row['revision'],2)
        with self.store.db(readonly=True) as db:
            self.assertEqual(db.execute('SELECT balance FROM eco_accounts WHERE user_id=1').fetchone()[0],10000)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_ledger').fetchone()[0],0)

    async def test_failed_public_update_is_queued_and_retries_without_saving_again(self):
        await self.install_modules()
        values=self.store.snapshot(fixtures.BASE)['systems']['feedback']|dict(outside_hours=2)
        view=await self.preview('feedback',values)
        self.system.refresh.side_effect=RuntimeError('temporary')
        await view.save.callback(self.interaction())
        self.assertEqual(self.store.history()[0]['sync_state'],'pending')
        self.assertEqual(self.store.snapshot(fixtures.BASE)['systems']['feedback']['outside_hours'],2)
        self.system.refresh.side_effect=None
        await self.system.flush(self.guild,view.draft)
        self.assertEqual(self.store.history()[0]['sync_state'],'done')
        self.assertEqual(self.store.snapshot(fixtures.BASE)['revision'],1)
        self.assertEqual(len(self.store.history()),1)
        completed_calls=self.system.refresh.await_count
        await self.system.flush(self.guild,view.draft)
        self.assertEqual(self.system.refresh.await_count,completed_calls)

    async def test_restore_only_changes_the_selected_settings_and_requires_confirmation(self):
        await self.install_modules()
        before=self.store.snapshot(fixtures.BASE)
        view=await self.preview('ticket_attention',before['systems']['ticket_attention']|dict(max_open=2))
        await view.save.callback(self.interaction());op=self.store.history()[0]['op']
        self.store.apply('schedule','20:00',1,1,'unrelated',now=fixtures.BASE)
        draft=await self.system.restore_draft(op)
        self.assertEqual(self.tickets.config('max_open'),'2')
        confirm=ConfirmSettings(self.system,1,self.interaction(),draft)
        await confirm.save.callback(self.interaction())
        self.assertEqual(self.tickets.config('max_open'),'3')
        self.assertEqual(self.store.snapshot(fixtures.BASE)['values']['daily_server_up_time'],'20:00')

    async def test_searchable_directory_contains_real_subcommands_and_section_filters(self):
        class Command:
            id=123
            def to_dict(self):return dict(name='ticket',description='Atención',options=[dict(type=1,name='buscar',description='Buscar tickets por jugador'),dict(type=1,name='prioridad',description='Cambiar la prioridad')])
        self.system.index_commands([Command()])
        self.assertEqual(self.system.functions('JUGADOR')[0]['mention'],'</ticket buscar:123>')
        self.assertEqual(len(self.system.functions('@tickets')),2)
        self.assertFalse(self.system.functions('@backups'))
        i=self.interaction();await self.system.open(i,'directory',query='prioridad')
        self.assertIn('</ticket prioridad:123>',str(i.edit_original_response.call_args.kwargs['view'].to_components()))

    async def test_saved_limits_are_used_by_actual_report_suggestion_and_feedback_flows(self):
        await self.install_modules()
        def save(key,changes,token):
            state=self.store.snapshot(fixtures.BASE)
            self.store.apply('system',state['systems'][key]|changes,state['revision'],1,token,target=key,now=fixtures.BASE,expected_fields=state['systems'][key])
        draft=self.bugs.begin(1)
        save('bugs',dict(accepting=False),'bugs')
        self.assertEqual(self.bugs.begin(1),draft)
        with self.assertRaisesRegex(ValueError,'recibiendo'):self.bugs.begin(2)
        save('suggestions',dict(accepting=False),'suggestions')
        with self.assertRaisesRegex(ValueError,'recibiendo'):self.suggestions.create('request',2,'Idea válida','Una propuesta suficientemente detallada')
        save('feedback',dict(outside_hours=1),'feedback')
        self.feedback.save(1,5,'Todo bien','private',staff=2,topic='Atención por voz',now=fixtures.BASE)
        self.feedback.save(1,4,'Todo bien otra vez','private',staff=2,topic='Otra ayuda por voz',now=fixtures.BASE+3601)

    async def test_photo_limits_preserve_duplicate_delivery_and_existing_entries(self):
        state=self.store.snapshot(fixtures.BASE);values=state['systems']['photo_entries']|dict(weekly_limit=1)
        self.store.apply('system',values,0,1,'photos',target='photo_entries',now=fixtures.BASE)
        first=self.photos.upload(10,20,1,'a.png','https://example.com/a',b'image',now=fixtures.BASE)
        self.assertEqual(self.photos.upload(10,20,1,'a.png','https://example.com/a',b'image',now=fixtures.BASE),first)
        with self.assertRaisesRegex(ValueError,'límite'):self.photos.upload(11,21,1,'b.png','https://example.com/b',b'image',now=fixtures.BASE)
        self.assertEqual(len(self.photos.entries()),1)

    async def test_validation_rejects_unknown_fields_limits_and_wildcard_filters(self):
        state=self.store.snapshot(fixtures.BASE)
        for key,changes in (('ticket_files',dict(max_file_mb=120,max_case_mb=20)),('security',dict(words='*')),
                            ('ticket_attention',dict(max_open=0)),('games',dict(interval_hours=0))):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):validate(key,state['systems'][key]|changes)
        with self.assertRaises(ValueError):validate('security',state['systems']['security']|dict(token='secret'))
        self.assertEqual(self.store.snapshot(fixtures.BASE)['revision'],0)

    async def test_game_settings_change_real_turns_without_changing_the_25_coin_reward(self):
        from test_minigames import QUESTIONS
        await self.install_modules();games=MinigameStore(self.path);games.initialize(QUESTIONS)
        row=games.open(1,'acertijo',now=fixtures.BASE)
        state=self.store.snapshot(fixtures.BASE)
        values=state['systems']['games']|dict(interval_hours=2,acertijo_enabled=False)
        self.store.apply('system',values,0,1,'games',target='games',now=fixtures.BASE)
        with self.assertRaisesRegex(ValueError,'pausado'):games.open(2,'acertijo',now=fixtures.BASE)
        result=games.answer(1,row['id'],'río','answer',99,now=fixtures.BASE)
        self.assertEqual(result['coins'],25)
        self.assertEqual(result['next_at'],fixtures.BASE+7200)
        self.assertFalse(games.availability(1,fixtures.BASE+7199)['available'])
        self.assertTrue(games.availability(1,fixtures.BASE+7200)['available'])

    async def test_streamer_settings_preserve_the_existing_role_reference(self):
        from settings_catalog import GUILD
        with self.store.db() as db:
            db.execute('CREATE TABLE streamer_config(guild INTEGER PRIMARY KEY,role INTEGER,minimum INTEGER)')
            db.execute('INSERT INTO streamer_config VALUES (?,?,50)',(GUILD,1568399564887826486))
        state=self.store.snapshot(fixtures.BASE)
        self.store.apply('system',state['systems']['streams']|dict(minimum=100),0,1,'streams',target='streams',now=fixtures.BASE)
        with self.store.db(readonly=True) as db:
            self.assertEqual(tuple(db.execute('SELECT role,minimum FROM streamer_config').fetchone()),(1568399564887826486,100))

    async def test_backup_keeps_settings_jobs_and_unsynced_changes_for_restart(self):
        from backup import snapshot
        await self.install_modules()
        state=self.store.snapshot(fixtures.BASE)
        self.store.apply('system',state['systems']['suggestions']|dict(accepting=False),0,1,'pending',target='suggestions',now=fixtures.BASE)
        path=self.path.with_name('settings-backup.db');snapshot(self.path,path)
        recovered=SettingsStore(path);recovered.initialize()
        self.assertEqual(recovered.pending()[0]['op'],'pending')
        self.assertFalse(recovered.snapshot(fixtures.BASE)['systems']['suggestions']['accepting'])
        self.assertEqual(recovered.snapshot(fixtures.BASE)['revision'],1)
