import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock,patch

import discord
from backup import snapshot
from bot_settings import SettingsStore,DEFAULTS,TEXT_KEYS,photo_week,parse_hour,validate_values
from daily_up import daily_up_embed
from economy_store import EconomyStore,SCHEMA
from photo_store import PhotoStore,week_bounds
from settings_panel import SettingsPanel,SettingsForm,ConfirmSettings,Draft,RootView
from photos import PhotoSystem
from economy import shop_embed
from community_features import CommunityFeatures

BASE=1794232800
GUILD=1244988345327550565


class SettingsFixtures:
    def setup_store(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'bot.db'
        self.photos=PhotoStore(self.path);self.photos.initialize(BASE)
        self.store=SettingsStore(self.path);self.store.initialize()
        self.week,_,self.end=week_bounds(BASE)
        self.next_week=photo_week(BASE,1)


class SettingsStoreTests(SettingsFixtures,unittest.TestCase):
    def setUp(self):self.setup_store()

    def test_defaults_preserve_the_approved_rewards_and_server_up(self):
        state=self.store.snapshot(BASE)
        self.assertEqual(state['rewards'],[500,300,150]);self.assertEqual(state['next_rewards'],[500,300,150])
        self.assertEqual(state['values'],DEFAULTS);self.assertEqual(state['revision'],0)

    def test_scheduled_prizes_are_used_by_real_payouts_only_from_the_selected_week(self):
        self.store.apply('rewards',[800,500,250],0,9,'next',target=self.next_week,now=BASE)
        self.assertEqual(self.photos.reward_rates(self.week),(500,300,150))
        self.assertEqual(self.photos.reward_rates(self.next_week),(800,500,250))
        with self.photos.db() as db:
            for statement in SCHEMA.split(';'):
                if statement.strip():db.execute(statement)
        first=self.photos.register(10,20,1,'foto.png','https://cdn.discordapp.com/a',BASE,now=BASE)
        self.photos.vote(first,2,now=BASE)
        self.photos.reward_podium(self.week,99,now=self.end)
        second=self.photos.register(11,21,1,'foto.png','https://cdn.discordapp.com/a',self.end+10,now=self.end+10)
        self.photos.vote(second,2,now=self.end+11)
        self.photos.reward_podium(self.next_week,99,now=self.end+7*86400)
        self.assertEqual(EconomyStore(self.path).account(1)['balance'],1300)
        self.assertEqual(self.photos.ranking(self.week)[0]['coins'],500)

    def test_already_paid_week_cannot_be_repriced(self):
        with self.photos.db() as db:db.execute("INSERT INTO lv_photo_weeks(week,starts,ends,state,podium_closed) VALUES (?,?,?,'closed',?)",(self.week,BASE-10,self.end,BASE))
        with self.assertRaisesRegex(ValueError,'cerrada'):
            self.store.apply('rewards',[1000,600,400],0,9,'closed',target=self.week,now=BASE)
        self.assertEqual(self.store.snapshot(BASE)['revision'],0)
        self.assertEqual(self.photos.reward_rates(self.week),(500,300,150))

    def test_confirmation_is_idempotent_and_stale_panels_cannot_overwrite_a_change(self):
        first=self.store.apply('schedule','7:45 p. m.',0,9,'one',now=BASE)
        self.assertEqual(self.store.apply('schedule','7:45 p. m.',0,9,'one',now=BASE),first)
        with self.assertRaises(ValueError):self.store.apply('schedule','20:00',0,8,'stale',now=BASE)
        with self.assertRaises(ValueError):self.store.apply('schedule','7:45 p. m.',0,8,'one',now=BASE)
        self.assertEqual(self.store.snapshot(BASE)['values']['daily_server_up_time'],'19:45')
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM bot_setting_ops').fetchone()[0],1)

    def test_two_simultaneous_admins_cannot_both_save_the_same_revision(self):
        def save(n):
            try:self.store.apply('schedule',f'{19+n}:00',0,n,f'op{n}',now=BASE);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(save,(1,2))),1)
        self.assertEqual(self.store.snapshot(BASE)['revision'],1)

    def test_backup_preserves_settings_scheduled_prizes_receipts_and_the_daily_slot(self):
        with self.store.db() as db:db.execute('INSERT INTO settings VALUES (?,?)',('daily_server_up_slot','2026-11-09'))
        self.store.apply('rewards',[900,600,300],0,9,'prizes',target=self.next_week,now=BASE)
        self.store.apply('schedule','20:00',1,9,'hour',now=BASE)
        backup=self.path.with_name('backup.db');manifest=snapshot(self.path,backup)
        recovered=SettingsStore(backup);recovered.initialize()
        self.assertEqual(recovered.snapshot(BASE),self.store.snapshot(BASE))
        self.assertEqual(recovered.snapshot(BASE)['daily_slot'],'2026-11-09')
        self.assertEqual(manifest['rows']['bot_setting_ops'],2);self.assertEqual(manifest['rows']['lv_photo_reward_rates'],1)

    def test_invalid_rewards_hours_and_templates_never_change_the_settings(self):
        bad=[('rewards',[-1,1,1]),('rewards',[100,500,50]),('rewards',[1000001,20,10]),('rewards',[1.5,1,1]),
            ('rewards',[True,1,1]),('rewards','321'),('schedule','25:00'),('schedule','18:90'),('schedule','14:00 pm')]
        for kind,values in bad:
            with self.subTest(kind=kind,values=values):
                with self.assertRaises(ValueError):self.store.apply(kind,values,0,9,'bad',target=self.week,now=BASE)
        for body in ('sin enlace','{enlace.__class__}','{enlace!r}','{enlace} {secreto}','{enlace'):
            values={key:DEFAULTS[key] for key in TEXT_KEYS};values['daily_server_up_body']=body
            with self.assertRaises(ValueError):self.store.apply('text',values,0,9,'badtext',now=BASE)
        self.assertEqual(self.store.snapshot(BASE)['revision'],0)

    def test_human_hours_and_templates_render_the_real_join_link_and_selected_time(self):
        self.assertEqual(parse_hour('6:30 p. m.'),'18:30');self.assertEqual(parse_hour('12:00 am'),'00:00')
        self.assertEqual(validate_values('rewards',['1,000','600','300']),[1000,600,300])
        values={key:DEFAULTS[key] for key in TEXT_KEYS}
        values['daily_server_up_body']='Nos vemos a las {hora}, bro. {enlace}'
        self.store.apply('schedule','20:00',0,9,'time',now=BASE)
        self.store.apply('text',values,1,9,'text',now=BASE)
        state=self.store.snapshot(BASE)
        embed=daily_up_embed(lambda key,default='':state['values'].get(key,default),'https://cfx.re/join/test')
        self.assertIn('8:00 p. m.',embed.description);self.assertIn('https://cfx.re/join/test',embed.description)
        self.assertEqual(embed.color.value,0xE53935)

    def test_photos_shop_and_guide_all_show_the_saved_rewards_and_time(self):
        with self.photos.db() as db:
            for statement in SCHEMA.split(';'):
                if statement.strip():db.execute(statement)
        self.store.apply('rewards',[1000,600,400],0,9,'current',target=self.week,now=BASE)
        self.store.apply('schedule','20:00',1,9,'hour',now=BASE)
        economy=EconomyStore(self.path)
        photo_system=PhotoSystem(MagicMock(),self.path,GUILD)
        panel=photo_system.panel_embed(self.photos.current(BASE))
        self.assertIn('1000 monedas',str(panel.to_dict()))
        catalog=shop_embed(economy.rotation(now=BASE))
        self.assertIn('1000 monedas',str(catalog.to_dict()))
        with patch('bot_settings.time.time',return_value=BASE):
            guide=CommunityFeatures(SimpleNamespace(store=economy)).guide_embed()
        self.assertIn('1000 monedas',str(guide.to_dict()));self.assertIn('8:00 p. m.',str(guide.to_dict()))


class SettingsUITests(SettingsFixtures,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_store()
        clock=patch('bot_settings.time.time',return_value=BASE);clock.start();self.addCleanup(clock.stop)
        self.bot=SimpleNamespace(changes=SimpleNamespace(tracked=AsyncMock(side_effect=self.tracked)))
        self.system=SettingsPanel(self.bot,self.path,GUILD,'https://cfx.re/join/57vjg7')
        self.system.refresh=AsyncMock();self.snapshots=[]
        self.member=SimpleNamespace(id=1,guild_permissions=discord.Permissions(administrator=True))
        self.guild=SimpleNamespace(id=GUILD,fetch_member=AsyncMock(return_value=self.member))

    async def tracked(self,env,title,operation,*,request_id,snapshot):
        self.snapshots.append(await snapshot());result=await operation();self.snapshots.append(await snapshot());return result

    def interaction(self,user=None,guild=GUILD):
        i=MagicMock();i.user=user or self.member;i.guild=self.guild;i.guild_id=guild
        i.response.is_done.return_value=False;i.response.defer=AsyncMock();i.response.send_message=AsyncMock()
        i.followup.send=AsyncMock();i.edit_original_response=AsyncMock()
        return i

    async def preview(self):
        state=self.store.snapshot(BASE);form=SettingsForm(self.system,1,state,'schedule')
        form.fields[0]._value='7:45 pm';i=self.interaction();await form.on_submit(i)
        return i.edit_original_response.call_args.kwargs['view']

    async def test_form_submission_only_previews_and_save_requires_a_separate_click(self):
        view=await self.preview()
        self.assertIsInstance(view,ConfirmSettings);self.assertEqual(self.store.snapshot(BASE)['revision'],0)
        self.bot.changes.tracked.assert_not_awaited()
        click=self.interaction();await view.save.callback(click)
        self.assertEqual(self.store.snapshot(BASE)['values']['daily_server_up_time'],'19:45')
        self.assertEqual(len(self.snapshots),2);self.assertEqual(self.snapshots[0]['settings']['revision'],0)
        self.assertEqual(self.snapshots[1]['settings']['revision'],1)
        self.assertTrue(self.snapshots[1]['receipt']);self.system.refresh.assert_awaited_once()
        self.assertFalse(click.edit_original_response.call_args.kwargs['allowed_mentions'].everyone)

    async def test_cancel_and_unauthorized_users_cannot_save_the_preview(self):
        view=await self.preview();other=self.interaction(SimpleNamespace(id=2,guild_permissions=discord.Permissions(administrator=True)))
        self.assertFalse(await view.interaction_check(other))
        await view.save.callback(other);self.assertEqual(self.store.snapshot(BASE)['revision'],0)
        await view.cancel.callback(self.interaction());self.assertEqual(self.store.snapshot(BASE)['revision'],0)
        self.bot.changes.tracked.assert_not_awaited()

    async def test_losing_admin_access_before_confirmation_is_rechecked_from_discord(self):
        view=await self.preview()
        self.guild.fetch_member.return_value=SimpleNamespace(id=1,guild_permissions=discord.Permissions.none())
        click=self.interaction();await view.save.callback(click)
        self.assertEqual(self.store.snapshot(BASE)['revision'],0);self.bot.changes.tracked.assert_not_awaited()
        self.assertIn('administradores',click.edit_original_response.call_args.kwargs['content'])

    async def test_stale_confirmation_cannot_overwrite_another_admins_hour(self):
        view=await self.preview();self.store.apply('schedule','21:00',0,2,'other',now=BASE)
        await view.save.callback(self.interaction())
        self.assertEqual(self.store.snapshot(BASE)['values']['daily_server_up_time'],'21:00')
        self.assertIsNone(self.store.receipt(view.draft.token))

    async def test_two_clicks_only_commit_one_receipt(self):
        view=await self.preview()
        await asyncio.gather(view.save.callback(self.interaction()),view.save.callback(self.interaction()))
        self.assertEqual(self.store.snapshot(BASE)['revision'],1)
        self.assertEqual(self.bot.changes.tracked.await_count,1)

    async def test_panel_is_private_and_citizens_and_other_servers_are_rejected(self):
        command=self.system.group.get_command('panel')
        i=self.interaction();await command.callback(i)
        self.assertTrue(i.response.defer.call_args.kwargs['ephemeral'])
        self.assertIsInstance(i.edit_original_response.call_args.kwargs['view'],RootView)
        with self.assertRaises(ValueError):await self.system.authorize(self.interaction(guild=123))
        self.guild.fetch_member.return_value=SimpleNamespace(id=1,guild_permissions=discord.Permissions.none())
        with self.assertRaises(ValueError):await command.callback(self.interaction())
        self.assertTrue(self.system.group.default_permissions.administrator)
