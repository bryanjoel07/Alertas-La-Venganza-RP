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
from economy_store import SCHEMA, EconomyStore
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

    def test_pending_upload_survives_backup_and_is_bound_to_its_single_bot_post(self):
        entry=self.store.upload(800,900,1,'foto.png','https://cdn.discordapp.com/upload',b'image',now=BASE)
        backup=self.path.with_name('pending.db');snapshot(self.path,backup)
        recovered=PhotoStore(backup);recovered.initialize(BASE)
        self.assertEqual(recovered.entry(entry)['media'],b'image')
        recovered.posted(entry,1000,1001,'https://cdn.discordapp.com/published')
        row=recovered.entry(entry)
        self.assertEqual((row['source'],row['control'],row['attachment']),(1000,1000,1001))
        self.assertIsNone(row['media']);self.assertEqual(row['author'],1)

    def test_repeated_submission_reuses_its_entry_and_pending_limit_does_not_block_retries(self):
        first=self.store.upload(800,900,1,'foto.png','https://cdn.discordapp.com/upload',b'image',now=BASE)
        for key in (801,802):self.store.upload(key,900,1,'foto.png','https://cdn.discordapp.com/upload',b'image',now=BASE)
        self.assertEqual(self.store.upload(800,900,1,'foto.png','https://cdn.discordapp.com/upload',b'image',now=BASE),first)
        with self.assertRaises(ValueError):self.store.upload(803,900,1,'foto.png','https://cdn.discordapp.com/upload',b'image',now=BASE)

    def test_pending_upload_that_crosses_the_week_boundary_enters_the_new_round(self):
        entry=self.store.upload(800,900,1,'foto.png','https://cdn.discordapp.com/upload',b'image',now=self.end-1)
        self.store.posting(entry,self.end+1)
        row=self.store.entry(entry)
        self.assertEqual(row['week'],week_bounds(self.end+1)[0]);self.assertGreater(row['ends'],self.end+1)


class PhotoServiceFixtures:
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.bot = MagicMock(); self.bot.user.id = 99
        self.bot.http.get_from_cdn=AsyncMock(return_value=b'image bytes')
        self.system = PhotoSystem(self.bot, Path(temp.name)/'photos.db', GUILD)
        self.system.store.initialize(BASE)
        self.bot.economy.store=EconomyStore(self.system.store.path)
        with self.system.store.db() as db:
            for statement in SCHEMA.split(';'):
                if statement.strip():db.execute(statement)
        self.clock = patch('photos.time.time', return_value=BASE); self.clock.start(); self.addCleanup(self.clock.stop)
        self.channel = MagicMock(spec=discord.TextChannel); self.channel.id = FOTOS_CHANNEL; self.channel.name = '📸┊𝐅𝐨𝐭𝐨𝐬'
        self.guild = SimpleNamespace(id=GUILD, me=SimpleNamespace(id=99), filesize_limit=100000)
        self.system.member_directory.load=AsyncMock(return_value=[])
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
            _state=SimpleNamespace(http=self.bot.http),
            channel=self.channel, created_at=datetime.fromtimestamp(created, timezone.utc), attachments=list(attachments),
            embeds=[], components=[], pinned=False, reference=None, content='',edit=AsyncMock(), delete=AsyncMock(), pin=AsyncMock(), unpin=AsyncMock())
        row.reply = AsyncMock(side_effect=self.send)
        async def edit(**kwargs):
            self.decorate(row, kwargs); return row
        async def pin(**kwargs): row.pinned=True
        async def unpin(**kwargs): row.pinned=False
        async def remove(**kwargs): self.messages.pop(row.id,None)
        row.edit.side_effect=edit; row.pin.side_effect=pin; row.unpin.side_effect=unpin
        row.delete.side_effect=remove
        self.messages[key] = row
        return row

    def decorate(self, row, kwargs):
        if 'embed' in kwargs: row.embeds=[kwargs['embed']]
        if 'content' in kwargs: row.content=kwargs['content'] or ''
        if kwargs.get('view'):
            ids=[c.custom_id for c in kwargs['view'].children]
            row.components=[SimpleNamespace(children=[SimpleNamespace(custom_id=value) for value in ids],to_dict=lambda:{'type':1,'components':[{'type':2,'custom_id':value} for value in ids]})]

    async def send(self, **kwargs):
        row=self.message(99, created=int(time.time())); self.decorate(row, kwargs)
        if kwargs.get('file'):
            row.attachments=[SimpleNamespace(id=row.id+1000,filename=kwargs['file'].filename,content_type='image/png',width=100,height=100,size=10,
                url=f'https://cdn.discordapp.com/attachments/{FOTOS_CHANNEL}/{row.id+1000}/{kwargs["file"].filename}',read=AsyncMock(return_value=b'image bytes'))]
        return row

    def source(self, owner=1, created=BASE, count=1):
        files=[SimpleNamespace(id=200+n, filename=f'foto{n}.png', url=f'https://cdn.discordapp.com/foto{n}.png',
            content_type='image/png', width=100, height=100, size=10, read=AsyncMock(return_value=b'image bytes')) for n in range(count)]
        return self.message(owner, files, created)

    def interaction(self, row, user=2):
        self.serial+=1
        i=MagicMock(id=discord.utils.time_snowflake(datetime.fromtimestamp(int(time.time()),timezone.utc))+self.serial,guild_id=GUILD,channel_id=FOTOS_CHANNEL,
            user=SimpleNamespace(id=user,bot=False,guild_permissions=discord.Permissions()), message=row)
        i.response.is_done.return_value=False; i.response.defer=AsyncMock(); i.response.send_message=AsyncMock();i.response.send_modal=AsyncMock(); i.followup.send=AsyncMock()
        return i

