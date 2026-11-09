import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from backup import snapshot
from economy_store import SCHEMA
from photo_store import PhotoStore, week_bounds
from photos import PhotoSystem, PhotoButton, PhotoControls, FOTOS_CHANNEL

BASE = int(datetime.fromisoformat('2026-11-09T14:00:00+00:00').timestamp())
GUILD = 1244988345327550565


class PhotoStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'photos.db'
        self.store = PhotoStore(self.path); self.store.initialize(BASE)
        self.week, self.start, self.end = week_bounds(BASE)

    def photo(self, source=10, attachment=20, owner=1, stamp=BASE):
        return self.store.register(source, attachment, owner, 'foto.png', 'https://cdn.discordapp.com/foto.png', stamp, now=BASE+100)

    def test_week_boundaries_are_monday_midnight_in_puerto_rico(self):
        self.assertEqual(self.week, '2026-11-09')
        self.assertEqual(datetime.fromtimestamp(self.start, timezone.utc).hour, 4)
        self.assertEqual(week_bounds(self.end-1)[0], self.week)
        self.assertEqual(week_bounds(self.end)[0], '2026-11-16')
        self.assertEqual(week_bounds(self.start-1)[0], '2026-11-02')

    def test_existing_week_photos_register_once_per_attachment_and_older_ones_do_not(self):
        photo = self.photo(stamp=self.start+10)
        self.assertEqual(self.photo(stamp=self.start+10), photo)
        other = self.photo(attachment=21)
        self.assertNotEqual(photo, other)
        self.assertIsNone(self.photo(source=11, stamp=self.start-1))
        self.assertEqual(len(self.store.entries()), 2)

    def test_parallel_votes_are_one_per_person_per_photo_and_can_be_removed(self):
        entry = self.photo()
        with ThreadPoolExecutor(max_workers=6) as pool:
            changed = list(pool.map(lambda _: self.store.vote(entry, 2, now=BASE+200), range(6)))
        self.assertEqual(sum(changed), 1); self.assertEqual(self.store.entry(entry)['votes'], 1)
        another = self.photo(source=11, attachment=21)
        self.store.vote(another, 2, now=BASE+200)
        self.assertEqual(self.store.entry(another)['votes'], 1)
        self.assertTrue(self.store.vote(entry, 2, False, BASE+201))
        self.assertFalse(self.store.vote(entry, 2, False, BASE+202))
        with self.assertRaisesRegex(ValueError, 'propia'): self.store.vote(entry, 1, now=BASE+201)

    def test_vote_deadline_is_enforced_before_the_scheduler_disables_buttons(self):
        entry = self.photo()
        self.store.vote(entry, 2, now=self.end-1)
        with self.assertRaisesRegex(ValueError, 'terminó'): self.store.vote(entry, 3, now=self.end)
        with self.assertRaisesRegex(ValueError, 'terminó'): self.store.vote(entry, 2, False, self.end)
        self.assertEqual(self.store.entry(entry)['votes'], 1)

    def test_highest_votes_win_and_ties_use_the_earliest_photo(self):
        early = self.photo(stamp=BASE-10)
        later = self.photo(source=11, attachment=21, stamp=BASE)
        for entry in (early, later): self.store.vote(entry, 2, now=BASE+200)
        self.assertEqual(self.store.freeze(self.week, self.end)['winner'], early)
        self.store.deleted(10)
        self.assertEqual(self.store.freeze(self.week, self.end)['winner'], later)
        self.store.published(self.week, 100)
        self.store.deleted(11)
        self.assertEqual(self.store.freeze(self.week, self.end+1)['winner'], later)

    def test_removing_an_attachment_or_original_disqualifies_it_but_preserves_vote_records(self):
        first = self.photo(); second = self.photo(attachment=21)
        self.store.vote(first, 2, now=BASE+200)
        self.store.sync_source(10, {21})
        with self.assertRaises(ValueError): self.store.vote(first, 3, now=BASE+200)
        self.assertEqual(self.store.entry(first)['votes'], 1)
        self.assertEqual(self.store.entry(second)['active'], 1)
        self.store.deleted(10)
        self.assertEqual(self.store.entry(second)['active'], 0)
        self.assertIsNone(self.store.freeze(self.week, self.end)['winner'])

    def test_votes_and_pending_publication_survive_backup_and_restart(self):
        entry = self.photo(); self.store.vote(entry, 2, now=BASE+200)
        self.store.freeze(self.week, self.end); self.store.stage(self.week, b'original image', 'winner.png', 'https://cdn.discordapp.com/winner')
        self.store.publishing(self.week, self.end+1)
        target = self.path.with_name('backup.db'); manifest = snapshot(self.path, target)
        recovered = PhotoStore(target); recovered.initialize(self.end+100)
        self.assertEqual(recovered.entry(entry)['votes'], 1)
        self.assertEqual(recovered.week(self.week)['image'], b'original image')
        self.assertEqual(manifest['rows']['lv_photo_votes'], 1)
        recovered.published(self.week, 999)
        self.assertFalse(recovered.due(self.end+100)); self.assertIsNone(recovered.week(self.week)['image'])

    def prize_catalog(self):
        with self.store.db() as db:
            for statement in SCHEMA.split(';'):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO eco_products(sku,name,kind,tier,price,payload,stock) VALUES ('banner','Banner rojo','banner','profile',900,'{}',2)")

    def test_prize_grants_once_without_charging_or_equipping_anything(self):
        self.prize_catalog(); entry = self.photo(); self.store.vote(entry, 2, now=BASE+200)
        self.store.prize(self.week, 'banner', 5, BASE+200)
        self.assertIsNone(self.store.award(self.week, 99, BASE+300))
        self.store.freeze(self.week, self.end); self.store.published(self.week, 900)
        receipt = self.store.award(self.week, 99, self.end+1)
        self.assertEqual(self.store.award(self.week, 99, self.end+2), receipt)
        with self.store.db() as db:
            purchase = db.execute('SELECT * FROM eco_purchases').fetchone()
            self.assertEqual(purchase['recipient'], 1); self.assertEqual(purchase['price'], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_accounts').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_equipped').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT stock FROM eco_products').fetchone()[0], 1)
        with self.assertRaises(ValueError): self.store.prize(self.week, None, 5)

    def test_duplicate_owned_or_unavailable_prizes_are_not_charged_or_duplicated(self):
        self.prize_catalog(); entry = self.photo(); self.store.vote(entry, 2, now=BASE+200)
        self.store.prize(self.week, 'banner', 5); self.store.freeze(self.week, self.end); self.store.published(self.week, 900)
        self.store.award(self.week, 99, self.end+1)
        next_entry = self.store.register(11, 21, 1, 'new.png', 'https://cdn.discordapp.com/new.png', self.end+10, now=self.end+10)
        next_week = week_bounds(self.end)[0]
        self.store.vote(next_entry, 2, now=self.end+20); self.store.prize(next_week, 'banner', 5)
        self.store.freeze(next_week, self.end+7*86400); self.store.published(next_week, 901)
        with self.assertRaisesRegex(ValueError, 'ya tiene'): self.store.award(next_week, 99, self.end+7*86400+1)
        with self.store.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_purchases').fetchone()[0], 1)


class PhotoServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.bot = MagicMock(); self.bot.user.id = 99
        self.system = PhotoSystem(self.bot, Path(temp.name)/'photos.db', GUILD)
        self.system.store.initialize(BASE)
        self.clock = patch('photos.time.time', return_value=BASE); self.clock.start(); self.addCleanup(self.clock.stop)
        self.channel = MagicMock(spec=discord.TextChannel); self.channel.id = FOTOS_CHANNEL; self.channel.name = '📸┊𝐅𝐨𝐭𝐨𝐬'
        self.guild = SimpleNamespace(id=GUILD, me=SimpleNamespace(id=99), filesize_limit=100000)
        self.channel.guild = self.guild
        self.channel.permissions_for = lambda user: discord.Permissions.all()
        self.messages = {}; self.serial = 0; self.tracked = []
        self.bot.fetch_channel = AsyncMock(return_value=self.channel)
        self.channel.fetch_message = AsyncMock(side_effect=self.fetch)
        self.channel.send = AsyncMock(side_effect=self.send)
        self.channel.history = self.history
        async def tracked(env, title, operation, **kwargs):
            before = await kwargs['snapshot'](); self.tracked.append(before)
            return await operation()
        self.bot.changes.tracked = tracked

    async def fetch(self, key):
        if key not in self.messages: raise discord.NotFound(SimpleNamespace(status=404, reason='Missing'), 'missing')
        return self.messages[key]

    async def history(self, **kwargs):
        after = kwargs.get('after')
        lower = after.id if isinstance(after, discord.Object) else discord.utils.time_snowflake(after) if after else 0
        rows = sorted(list(self.messages.values()), key=lambda m:m.id, reverse=not kwargs.get('oldest_first', False))
        for row in rows[:kwargs.get('limit') or len(rows)]:
            if row.id > lower: yield row

    def message(self, owner, attachments=(), created=BASE):
        self.serial += 1
        key = discord.utils.time_snowflake(datetime.fromtimestamp(created, timezone.utc)) + self.serial
        row = SimpleNamespace(id=key, author=SimpleNamespace(id=owner, bot=owner==99), guild=self.guild,
            channel=self.channel, created_at=datetime.fromtimestamp(created, timezone.utc), attachments=list(attachments),
            embeds=[], components=[], pinned=False, edit=AsyncMock(), delete=AsyncMock(), pin=AsyncMock(), unpin=AsyncMock())
        row.reply = AsyncMock(side_effect=self.send)
        async def edit(**kwargs):
            self.decorate(row, kwargs); return row
        async def pin(**kwargs): row.pinned=True
        async def unpin(**kwargs): row.pinned=False
        row.edit.side_effect=edit; row.pin.side_effect=pin; row.unpin.side_effect=unpin
        self.messages[key] = row
        return row

    def decorate(self, row, kwargs):
        if 'embed' in kwargs: row.embeds=[kwargs['embed']]
        if kwargs.get('view'):
            row.components=[SimpleNamespace(children=[SimpleNamespace(custom_id=c.custom_id) for c in kwargs['view'].children])]

    async def send(self, **kwargs):
        row=self.message(99, created=int(time.time())); self.decorate(row, kwargs)
        if kwargs.get('file'):
            row.attachments=[SimpleNamespace(url=f'https://cdn.discordapp.com/copied/{row.id}.png')]
        return row

    def source(self, owner=1, created=BASE, count=1):
        files=[SimpleNamespace(id=200+n, filename=f'foto{n}.png', url=f'https://cdn.discordapp.com/foto{n}.png',
            content_type='image/png', width=100, height=100, size=10, read=AsyncMock(return_value=b'image bytes')) for n in range(count)]
        return self.message(owner, files, created)

    def interaction(self, row, user=2):
        i=MagicMock(guild_id=GUILD, channel_id=FOTOS_CHANNEL, user=SimpleNamespace(id=user,bot=False), message=row)
        i.response.is_done.return_value=False; i.response.defer=AsyncMock(); i.response.send_message=AsyncMock(); i.followup.send=AsyncMock()
        return i

    async def test_each_photo_gets_persistent_controls_and_originals_are_never_edited(self):
        source=self.source(count=2)
        await self.system.observe(source); await self.system.observe(source)
        rows=self.system.store.entries()
        self.assertEqual(len(rows),2); self.assertEqual(source.reply.await_count,2)
        source.edit.assert_not_awaited(); source.delete.assert_not_awaited()
        for row in rows:
            self.assertTrue(PhotoControls(row['id']).is_persistent())
            control=self.messages[row['control']]
            self.assertEqual([c.custom_id for r in control.components for c in r.children], [f"lv:photo:{row['id']}:vote",f"lv:photo:{row['id']}:remove"])
            for child in PhotoControls(row['id']).children:
                match=PhotoButton.__discord_ui_compiled_template__.fullmatch(child.custom_id)
                restored=await PhotoButton.from_custom_id(None,None,match)
                self.assertEqual(restored.entry,row['id'])

    async def test_votes_use_the_correct_channel_photo_and_live_source(self):
        source=self.source(); await self.system.observe(source); row=self.system.store.entries()[0]
        i=self.interaction(self.messages[row['control']])
        await self.system.vote(i,row['id'],True); await self.system.vote(i,row['id'],True)
        self.assertEqual(self.system.store.entry(row['id'])['votes'],1)
        await self.system.vote(i,row['id'],False)
        self.assertEqual(self.system.store.entry(row['id'])['votes'],0)
        i.channel_id=123
        with self.assertRaises(ValueError): await self.system.vote(i,row['id'],True)
        i.channel_id=FOTOS_CHANNEL; i.user.id=1
        with self.assertRaises(ValueError): await self.system.vote(i,row['id'],True)
        i.user.id=2; del self.messages[source.id]
        with self.assertRaisesRegex(ValueError,'retirada'): await self.system.vote(i,row['id'],True)
        self.assertFalse(self.system.store.entry(row['id'])['active'])

    async def test_wrong_guild_bot_and_non_images_are_ignored(self):
        source=self.source(); source.guild=SimpleNamespace(id=123)
        await self.system.observe(source)
        source.guild=self.guild; source.author.bot=True
        await self.system.observe(source)
        source.author.bot=False; source.attachments[0].filename='documento.pdf'; source.attachments[0].content_type='application/pdf'
        await self.system.observe(source)
        self.assertFalse(self.system.store.entries()); source.reply.assert_not_awaited()

    async def test_backfill_uses_this_week_and_keeps_all_original_posts(self):
        old=self.source(created=week_bounds(BASE)[1]-10)
        first=self.source(created=BASE-300); second=self.source(created=BASE-100)
        await self.system.scan(self.channel); await self.system.scan(self.channel)
        self.assertEqual(len(self.system.store.entries()),2)
        self.assertEqual(first.reply.await_count,1); self.assertEqual(second.reply.await_count,1); old.reply.assert_not_awaited()
        for source in (old,first,second): source.delete.assert_not_awaited(); source.edit.assert_not_awaited()

    async def test_recovery_finds_sent_controls_before_reposting_after_a_crash(self):
        source=self.source(); await self.system.observe(source)
        row=self.system.store.entries()[0]; original=row['control']
        self.system.store.control(row['id'],None)
        await self.system.observe(source)
        self.assertEqual(self.system.store.entry(row['id'])['control'],original)
        source.reply.assert_awaited_once()

    async def test_weekly_winner_is_copied_credited_pinned_and_published_once(self):
        source=self.source(); await self.system.observe(source)
        row=self.system.store.entries()[0]; self.system.store.vote(row['id'],2,now=BASE+100)
        week=self.system.store.current(BASE); end=week['ends']
        with patch('photos.time.time',return_value=end+1):
            await self.system.settle(self.channel,week)
            self.assertFalse(self.system.store.due(end+1))
        result=self.system.store.week(week['week']); winner=self.messages[result['announcement']]
        self.assertTrue(winner.pinned); self.assertIn('<@1>',winner.embeds[0].description)
        self.assertEqual(result['winning_votes'],1); self.assertEqual(len(winner.attachments),1)
        self.assertIsNone(result['image']); self.assertTrue(self.tracked)
        source.delete.assert_not_awaited(); source.edit.assert_not_awaited()
        args=self.channel.send.call_args.kwargs
        self.assertFalse(args['allowed_mentions'].everyone); self.assertFalse(args['allowed_mentions'].roles)

    async def test_deleted_leader_is_excluded_and_api_failures_do_not_disqualify_photos(self):
        first=self.source(); second=self.source(owner=3)
        await self.system.observe(first); await self.system.observe(second)
        entries=self.system.store.entries(); by_author={r['author']:r for r in entries}
        self.system.store.vote(by_author[1]['id'],2,now=BASE+100)
        self.system.store.vote(by_author[1]['id'],3,now=BASE+100)
        self.system.store.vote(by_author[3]['id'],2,now=BASE+100)
        week=self.system.store.current(BASE)
        self.channel.fetch_message.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'later')
        with patch('photos.time.time',return_value=week['ends']+1):
            with self.assertRaises(discord.Forbidden): await self.system.settle(self.channel,week)
        self.assertEqual(self.system.store.entry(by_author[1]['id'])['active'],1)
        self.channel.fetch_message.side_effect=self.fetch; del self.messages[first.id]
        with patch('photos.time.time',return_value=week['ends']+1): await self.system.settle(self.channel,week)
        self.assertEqual(self.system.store.week(week['week'])['winner'],by_author[3]['id'])

    async def test_published_message_is_reconciled_after_send_succeeds_but_database_write_fails(self):
        source=self.source(); await self.system.observe(source)
        row=self.system.store.entries()[0]; self.system.store.vote(row['id'],2,now=BASE+100)
        week=self.system.store.current(BASE)
        real=self.system.store.published
        with patch('photos.time.time',return_value=week['ends']+1),patch.object(self.system.store,'published',side_effect=RuntimeError('restart')):
            with self.assertRaises(RuntimeError): await self.system.settle(self.channel,week)
        count=self.channel.send.await_count
        with patch('photos.time.time',return_value=week['ends']+10):
            await self.system.settle(self.channel,self.system.store.week(week['week']))
        self.assertEqual(self.channel.send.await_count,count)
        self.assertEqual(self.system.store.week(week['week'])['state'],'published')

    async def test_ready_verifies_the_real_channel_buttons_and_commands_and_preserves_original(self):
        source=self.source()
        self.bot.tree.fetch_commands=AsyncMock(return_value=[SimpleNamespace(name='foto',to_dict=lambda:{'options':[{'name':'semana'},{'name':'premio'}]})])
        await self.system.ready()
        self.assertTrue(self.system.prepared)
        panel=self.messages[int(self.system.store.config('panel'))]
        self.assertFalse(panel.pinned)
        self.assertEqual(len(self.system.store.entries()),1)
        source.edit.assert_not_awaited();source.delete.assert_not_awaited()
        self.bot.edit_channel.assert_not_called();self.bot.create_text_channel.assert_not_called()
        count=source.reply.await_count
        await self.system.ready()
        self.assertEqual(source.reply.await_count,count)

    async def test_initial_panel_pin_is_undone_once_without_pinning_a_photo_or_its_controls(self):
        week=self.system.store.current(BASE)
        panel=self.message(99);panel.embeds=[self.system.panel_embed(week)];panel.pinned=True
        self.system.store.config('panel',panel.id)
        await self.system.panel(self.channel)
        self.assertFalse(panel.pinned);panel.unpin.assert_awaited_once();panel.pin.assert_not_awaited()
        self.assertTrue(self.tracked[0]['pinned'])
        await self.system.panel(self.channel)
        panel.unpin.assert_awaited_once()
        source=self.source();await self.system.observe(source)
        row=self.system.store.entries()[0];control=self.messages[row['control']]
        with self.assertRaisesRegex(ValueError,'cierre semanal'):await self.system.pin(control)
        control.pin.assert_not_awaited();source.pin.assert_not_awaited()

    async def test_removed_image_buttons_are_disabled_without_deleting_its_post(self):
        source=self.source();await self.system.observe(source)
        row=self.system.store.entries()[0];control=self.messages[row['control']]
        source.attachments=[]
        await self.system.observe(source)
        await self.system.refresh_controls(self.channel)
        view=control.edit.call_args.kwargs['view']
        self.assertTrue(all(c.item.disabled for c in view.children))
        source.edit.assert_not_awaited();source.delete.assert_not_awaited()

    async def test_empty_weeks_do_not_make_fake_winners_and_zero_votes_never_pick_a_random_photo(self):
        week=self.system.store.current(BASE)
        with patch('photos.time.time',return_value=week['ends']+1):await self.system.settle(self.channel,week)
        self.channel.send.assert_not_awaited()
        source=self.source(created=week['ends']+10)
        with patch('photos.time.time',return_value=week['ends']+10):await self.system.observe(source)
        next_week=self.system.store.current(week['ends']+10)
        with patch('photos.time.time',return_value=next_week['ends']+1):await self.system.settle(self.channel,next_week)
        self.assertIsNone(self.system.store.week(next_week['week'])['winner'])
        self.assertEqual(self.channel.send.await_count,1)
        self.assertNotIn('tu foto ganó',self.channel.send.call_args.kwargs['content'] or '')

    async def test_prize_selection_requires_economy_authorization_before_confirmation(self):
        i=self.interaction(None)
        self.bot.economy.authorized.side_effect=ValueError('Solo administradores')
        command=self.system.group.get_command('premio')
        with self.assertRaisesRegex(ValueError,'administradores'):await command.callback(i,'ninguno')
        i.response.send_message.assert_not_awaited()
        self.bot.economy.authorized.side_effect=None
        await command.callback(i,'ninguno')
        confirm=i.response.send_message.call_args.kwargs['view']
        self.bot.economy.authorized.side_effect=ValueError('Solo administradores')
        with self.assertRaisesRegex(ValueError,'administradores'):await confirm.action(i)
        self.assertIsNone(self.system.store.current(BASE)['prize_actor'])

