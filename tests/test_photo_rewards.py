from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import discord

from backup import snapshot
from economy_store import SCHEMA,EconomyStore
from photo_store import PhotoStore,COIN_REWARDS,week_bounds
import test_photos
from test_photos import PhotoServiceFixtures,BASE


class CoinFixtures:
    def install_economy(self):
        self.economy=EconomyStore(self.path)
        with self.store.db() as db:
            for statement in SCHEMA.split(';'):
                if statement.strip():db.execute(statement)

    def entry_with_votes(self,owner,count,number=None,stamp=BASE):
        number=number or owner
        entry=self.store.register(100+number,200+number,owner,'foto.png','https://cdn.discordapp.com/foto.png',stamp,now=BASE+100)
        for user in range(1000,1000+count):self.store.vote(entry,user,now=BASE+200)
        return entry


class PhotoCoinTests(CoinFixtures,unittest.TestCase):
    def setUp(self):
        test_photos.PhotoStoreTests.setUp(self);self.install_economy()

    def test_three_distinct_players_receive_500_300_150_from_their_best_photo(self):
        best=self.entry_with_votes(1,9,1)
        self.entry_with_votes(1,8,11)
        second=self.entry_with_votes(2,4)
        third=self.entry_with_votes(3,3)
        self.entry_with_votes(4,2)
        preview=self.store.ranking(self.week)
        self.assertEqual([r['id'] for r in preview],[best,second,third])
        self.assertEqual([self.economy.account(uid)['balance'] for uid in (1,2,3)], [0,0,0])
        podium=self.store.reward_podium(self.week,99,now=self.end)
        self.assertEqual([(r['author'],r['votes'],r['coins']) for r in podium],[(1,9,500),(2,4,300),(3,3,150)])
        self.assertEqual([self.economy.account(uid)['balance'] for uid in (1,2,3,4)], [500,300,150,0])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_ledger').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_equipped').fetchone()[0],0)

    def test_deadline_missing_votes_and_partial_podium_do_not_create_extra_payments(self):
        self.entry_with_votes(1,0)
        self.assertFalse(self.store.reward_podium(self.week,99,now=self.end-1))
        self.assertIsNone(self.store.week(self.week)['podium_closed'])
        self.entry_with_votes(2,1)
        podium=self.store.reward_podium(self.week,99,now=self.end)
        self.assertEqual([(r['author'],r['coins']) for r in podium],[(2,500)])
        self.assertEqual(self.economy.account(1)['balance'],0)

    def test_two_players_only_receive_the_first_and_second_prizes(self):
        self.entry_with_votes(1,2);self.entry_with_votes(2,1)
        self.assertEqual([r['coins'] for r in self.store.reward_podium(self.week,99,now=self.end)],[500,300])

    def test_no_votes_closes_with_no_accounts_or_made_up_winners(self):
        self.entry_with_votes(1,0)
        self.assertFalse(self.store.reward_podium(self.week,99,now=self.end))
        self.assertIsNotNone(self.store.week(self.week)['podium_closed'])
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_accounts').fetchone()[0],0)

    def test_tied_votes_use_earliest_photo_not_the_sum_of_an_authors_photos(self):
        late=self.entry_with_votes(1,3,stamp=BASE+5)
        early=self.entry_with_votes(2,3,stamp=BASE)
        self.entry_with_votes(1,3,number=11,stamp=BASE+10)
        self.assertEqual([r['id'] for r in self.store.ranking(self.week)],[early,late])

    def test_parallel_closes_retries_and_later_deletions_keep_the_same_receipts(self):
        for owner,count in ((1,3),(2,2),(3,1)):self.entry_with_votes(owner,count)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.store.reward_podium(self.week,99,now=self.end),range(6)))
        self.assertEqual([r['author'] for r in results[0]],[1,2,3])
        self.store.deleted(101)
        self.assertEqual(self.store.freeze(self.week,self.end)['winner'],results[0][0]['id'])
        self.assertEqual([r['id'] for r in self.store.ranking(self.week)],[r['id'] for r in results[0]])
        self.assertEqual([self.economy.account(uid)['balance'] for uid in (1,2,3)],list(COIN_REWARDS))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_ledger').fetchone()[0],3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lv_photo_actions WHERE action='podio_monedas'").fetchone()[0],1)

    def test_mid_payment_failure_rolls_back_the_entire_podium_and_all_balances(self):
        for owner,count in ((1,3),(2,2),(3,1)):self.entry_with_votes(owner,count)
        credit=EconomyStore.credit;calls=[]
        def fail_second(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('Database error')
            return credit(*args)
        with patch('photo_store.EconomyStore.credit',side_effect=fail_second):
            with self.assertRaises(RuntimeError):self.store.reward_podium(self.week,99,now=self.end)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_ledger').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM eco_accounts').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lv_photo_podium').fetchone()[0],0)
        self.assertIsNone(self.store.week(self.week)['podium_closed'])
        self.assertEqual(len(self.store.reward_podium(self.week,99,now=self.end)),3)

    def test_changed_or_deleted_candidates_abort_before_paying_or_staging_the_wrong_image(self):
        entry=self.entry_with_votes(1,2);self.entry_with_votes(2,1)
        self.store.deleted(101)
        with self.assertRaisesRegex(ValueError,'cambiaron'):
            self.store.reward_podium(self.week,99,expected=[(entry,1,2)],now=self.end,media=(b'wrong image','wrong.png','url'))
        self.assertIsNone(self.store.week(self.week)['image'])
        self.assertEqual(self.economy.account(1)['balance'],0)
        self.assertEqual(self.economy.account(2)['balance'],0)

    def test_backup_restores_rank_payments_and_the_restart_cannot_pay_again(self):
        for owner,count in ((1,3),(2,2),(3,1)):self.entry_with_votes(owner,count)
        self.store.reward_podium(self.week,99,now=self.end)
        backup=self.path.with_name('reward-backup.db');manifest=snapshot(self.path,backup)
        recovered=PhotoStore(backup);recovered.initialize(self.end+1)
        self.assertEqual(len(recovered.reward_podium(self.week,99,now=self.end+1)),3)
        self.assertEqual(manifest['rows']['lv_photo_podium'],3)
        self.assertEqual(manifest['rows']['eco_ledger'],3)
        self.assertEqual([EconomyStore(backup).account(uid)['balance'] for uid in (1,2,3)],list(COIN_REWARDS))
        self.assertEqual(recovered.reward_status()['paid_positions'],3)

    def test_winnings_are_spendable_in_the_existing_shop_and_leave_a_normal_receipt(self):
        self.entry_with_votes(1,1);self.store.reward_podium(self.week,99,now=self.end)
        with self.store.db() as db:
            db.execute("INSERT INTO eco_products(sku,name,kind,tier,price,payload) VALUES ('titulo','Título de perfil','title','profile',250,'{}')")
        quote=self.economy.quote(1,1,'titulo',now=self.end+1)
        receipt=self.economy.buy(quote['id'],1,now=self.end+2)
        self.assertEqual((receipt['recipient'],receipt['price']),(1,250))
        self.assertEqual(self.economy.account(1)['balance'],250)

    def test_old_or_previously_announced_weeks_are_not_paid_retroactively(self):
        self.entry_with_votes(1,1);self.store.freeze(self.week,self.end);self.store.published(self.week,999)
        self.assertFalse(self.store.reward_podium(self.week,99,now=self.end))
        previous,previous_start,previous_end=week_bounds(self.start-1)
        self.store.config('since',previous_start)
        entry=self.store.register(20,30,2,'old.png','https://cdn.discordapp.com/old',previous_start+1,now=previous_start+1)
        self.store.vote(entry,9,now=previous_end-1)
        self.assertFalse(self.store.reward_podium(previous,99,now=self.end))
        self.assertEqual(self.economy.account(1)['balance'],0);self.assertEqual(self.economy.account(2)['balance'],0)

    def test_a_new_week_can_pay_the_same_player_again_with_its_own_receipt(self):
        self.entry_with_votes(1,1);self.store.reward_podium(self.week,99,now=self.end)
        entry=self.store.register(999,999,1,'next.png','https://cdn.discordapp.com/next',self.end+10,now=self.end+10)
        self.store.vote(entry,2,now=self.end+20)
        week,_,end=week_bounds(self.end+10)
        self.store.reward_podium(week,99,now=end)
        self.assertEqual(self.economy.account(1)['balance'],1000)

    def test_conflicting_existing_receipt_cannot_be_reported_as_a_paid_prize(self):
        self.entry_with_votes(1,1)
        with self.store.db() as db:
            EconomyStore.credit(db,1,1,f'photo-coins:{self.week}:1','conflicting old receipt',99)
        with self.assertRaisesRegex(ValueError,'no coincide'):self.store.reward_podium(self.week,99,now=self.end)
        self.assertIsNone(self.store.week(self.week)['podium_closed'])
        self.assertEqual(self.economy.account(1)['balance'],1)


class PhotoPodiumServiceTests(PhotoServiceFixtures,unittest.IsolatedAsyncioTestCase):
    def entries(self,counts=(3,2,1)):
        result=[]
        for owner,count in enumerate(counts,1):
            source=self.source(owner=owner,created=BASE+owner)
            image=source.attachments[0]
            entry=self.system.store.register(source.id,image.id,owner,image.filename,image.url,BASE+owner,now=BASE+10)
            for uid in range(100,100+count):self.system.store.vote(entry,uid,now=BASE+100)
            result.append((entry,source))
        return result

    async def close(self):
        week=self.system.store.current(BASE)
        with patch('photos.time.time',return_value=week['ends']):
            await self.system.settle(self.channel,week)
        return self.system.store.week(week['week'])

    async def test_public_podium_mentions_only_winners_and_confirms_their_shop_balances(self):
        entries=self.entries((4,3,2,1));week=await self.close()
        self.assertEqual(week['state'],'published')
        message=self.messages[week['announcement']]
        field=next(f for f in message.embeds[0].fields if f.name=='🏅 Podio de la semana')
        self.assertIn('<@1>',field.value);self.assertIn('500 monedas',field.value)
        self.assertIn('<@2>',field.value);self.assertIn('300 monedas',field.value)
        self.assertIn('<@3>',field.value);self.assertIn('150 monedas',field.value)
        self.assertNotIn('<@4>',message.content)
        allowed=self.channel.send.call_args.kwargs['allowed_mentions']
        self.assertEqual({u.id for u in allowed.users},{1,2,3});self.assertFalse(allowed.everyone);self.assertFalse(allowed.roles)
        self.assertEqual([self.bot.economy.store.account(uid)['balance'] for uid in (1,2,3)],list(COIN_REWARDS))
        self.assertTrue(message.pinned)
        for _,original in entries:original.delete.assert_not_awaited();original.edit.assert_not_awaited()

    async def test_deleted_second_place_is_skipped_and_fourth_photo_gets_third_prize(self):
        entries=self.entries((4,3,2,1));self.messages.pop(entries[1][1].id)
        week=await self.close();ranking=self.system.store.ranking(week['week'])
        self.assertEqual([r['author'] for r in ranking],[1,3,4])
        self.assertEqual(self.bot.economy.store.account(2)['balance'],0)
        self.assertEqual(self.bot.economy.store.account(4)['balance'],150)

    async def test_temporary_discord_failure_does_not_disqualify_or_pay_anyone(self):
        self.entries();self.channel.fetch_message.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'temporary access')
        with self.assertRaises(discord.Forbidden):await self.close()
        self.assertIsNone(self.system.store.current(BASE)['podium_closed'])
        self.assertTrue(all(r['active'] for r in self.system.store.entries()))
        self.assertEqual(self.bot.economy.store.account(1)['balance'],0)

    async def test_accepted_announcement_recovers_after_restart_without_repaying_or_reposting(self):
        self.entries();week=self.system.store.current(BASE)
        with patch.object(self.system.store,'published',side_effect=RuntimeError('restart')):
            with self.assertRaises(RuntimeError):await self.close()
        self.assertEqual(self.channel.send.await_count,1)
        self.messages.pop(next(r['source'] for r in self.system.store.ranking(week['week']) if r['place']==1))
        completed=await self.close()
        self.assertEqual(self.channel.send.await_count,1)
        self.assertEqual(completed['state'],'published')
        self.assertEqual([self.bot.economy.store.account(uid)['balance'] for uid in (1,2,3)],list(COIN_REWARDS))

    async def test_publication_failure_retries_from_saved_image_even_if_original_is_then_removed(self):
        self.entries();self.channel.send.side_effect=discord.HTTPException(SimpleNamespace(status=503,reason='Unavailable'),'later')
        with self.assertRaises(discord.HTTPException):await self.close()
        week=self.system.store.current(BASE);self.assertIsNotNone(week['podium_closed'])
        first=self.system.store.ranking(week['week'])[0];self.messages.pop(first['source'])
        self.channel.send.side_effect=self.send
        completed=await self.close();self.assertEqual(completed['state'],'published')
        self.assertEqual(self.bot.economy.store.account(1)['balance'],500)

    async def test_no_votes_announces_no_winner_and_does_not_pin_or_pay(self):
        self.entries((0,0,0));week=await self.close()
        self.assertIsNone(week['winner']);self.assertIsNotNone(week['podium_closed'])
        message=self.messages[week['announcement']]
        self.assertFalse(message.pinned);self.assertIn('no hubo fotos con votos',message.embeds[0].description)
        self.assertFalse(self.channel.send.call_args.kwargs['allowed_mentions'].users)
        self.assertEqual(self.bot.economy.store.account(1)['balance'],0)

    async def test_before_deadline_there_is_no_publication_or_payment(self):
        self.entries();week=self.system.store.current(BASE)
        await self.system.settle(self.channel,week)
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.bot.economy.store.account(1)['balance'],0)

    async def test_optional_item_prize_still_works_alongside_the_three_coin_awards(self):
        self.entries();week=self.system.store.current(BASE)
        with self.system.store.db() as db:
            db.execute("INSERT INTO eco_products(sku,name,kind,tier,price,payload,stock) VALUES ('extra','Banner extra','banner','profile',900,'{}',1)")
        self.system.store.prize(week['week'],'extra',55)
        closed=await self.close();await self.system.deliver_prize(self.channel,closed)
        self.assertEqual(self.bot.economy.store.account(1)['balance'],500)
        self.assertEqual(self.bot.economy.store.inventory(1)[0]['sku'],'extra')
        message=self.messages[closed['announcement']]
        self.assertTrue(any(f.name=='🏅 Podio de la semana' for f in message.embeds[0].fields))
        self.assertEqual(message.embeds[0].image.url,'attachment://'+message.attachments[0].filename)
        self.assertNotIn('attachments',message.edit.call_args.kwargs)
