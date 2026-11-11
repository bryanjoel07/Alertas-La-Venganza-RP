from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,Mock,patch

import discord
from economy_store import SCHEMA,EconomyStore
from minigame_catalog import load_bank,ASSETS
from minigame_store import MinigameStore,ANSWER_INTERVAL,AnswerWait,normalize
from minigame_ui import GamePanel,AnswerForm,controls,GameAction
from minigames import MinigameSystem,GENERAL
from backup import snapshot

QUESTIONS=[
 dict(id='foto01',kind='foto',prompt='¿Qué lugar es?',answer='Muelle de Del Perro',aliases=['Muelle de Del Perro','Del Perro Pier'],explanation='Es el muelle.'),
 dict(id='foto02',kind='foto',prompt='¿Qué lugar es?',answer='Monte Chiliad',aliases=['Monte Chiliad','Chiliad'],explanation='Es Chiliad.'),
 dict(id='rol01',kind='roleplay',prompt='¿Qué significa usar información OOC?',answer='Metagaming',aliases=['Metagaming','MG'],explanation='Usar información OOC.'),
 dict(id='acert01',kind='acertijo',prompt='¿Qué es?',answer='Un río',aliases=['Un río','río'],explanation='El río.'),
]

class GameStoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite';self.store=MinigameStore(self.path)
  with closing(sqlite3.connect(self.path)) as db:db.executescript(SCHEMA)
  self.store.initialize(QUESTIONS);self.eco=EconomyStore(self.path)
 def tearDown(self):self.tmp.cleanup()
 def test_reward_is_exactly_25_in_the_existing_shop_account(self):
  row=self.store.open(99,'acertijo');result=self.store.answer(99,row['id'],'es un RIO','interaction1',555,now=100)
  self.assertEqual(result['coins'],25);self.assertEqual(self.eco.account(99)['balance'],25)
  self.assertEqual(self.store.audit()['invalid_rewards'],0)
 def test_wrong_answer_does_not_pay_or_reveal_the_solution(self):
  row=self.store.open(99,'roleplay');result=self.store.answer(99,row['id'],'Powergaming','attempt1',555,now=100)
  self.assertEqual(result['state'],'wrong');self.assertNotIn('answer',result);self.assertEqual(self.eco.account(99)['balance'],0)
  self.assertEqual(self.store.get(row['id'],99)['status'],'active')
 def test_one_question_pays_once_for_each_player(self):
  for user in (99,100):
   row=self.store.open(user,'acertijo');self.store.answer(user,row['id'],'rio',str(user),555,now=100)
   replay=self.store.answer(user,row['id'],'rio',str(user)+'old',555,now=120)
   self.assertEqual(replay['coins'],0);self.assertEqual(replay['state'],'already');self.assertIsNone(self.store.open(user,'acertijo'))
   self.assertEqual(self.eco.account(user)['balance'],25)
 def test_duplicate_interaction_returns_receipt_without_second_payment(self):
  row=self.store.open(99,'roleplay');first=self.store.answer(99,row['id'],'mg','same',555,now=100)
  second=self.store.answer(99,row['id'],'mg','same',555,now=101)
  self.assertEqual(first['coins'],25);self.assertTrue(second['replayed']);self.assertEqual(self.eco.account(99)['balance'],25)
 def test_concurrent_answers_cannot_double_credit(self):
  row=self.store.open(99,'roleplay')
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(lambda op:self.store.answer(99,row['id'],'mg',op,555,now=100),('one','two')))
  self.assertEqual(sum(r['coins'] for r in results),25);self.assertEqual(self.eco.account(99)['balance'],25)
 def test_concurrent_open_returns_one_active_question(self):
  with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(lambda _:self.store.open(99,'foto'),range(3)))
  self.assertEqual(len({r['id'] for r in rows}),1)
 def test_another_user_cannot_answer_skip_or_read_the_question(self):
  row=self.store.open(99,'foto')
  with self.assertRaises(ValueError):self.store.get(row['id'],100)
  with self.assertRaises(ValueError):self.store.open(100,'foto',previous=row['id'],skip=True)
  with self.assertRaises(ValueError):self.store.answer(100,row['id'],'Chiliad','forged',555,now=100)
 def test_wrong_guess_consumes_the_turn_across_all_modes_for_exactly_12_hours(self):
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'Wrong','first',555,now=100)
  other=self.store.open(99,'acertijo')
  with self.assertRaises(ValueError):self.store.answer(99,other['id'],'rio','fast',555,now=101)
  with self.assertRaises(AnswerWait):self.store.answer(99,other['id'],'rio','still-early',555,now=100+ANSWER_INTERVAL-1)
  result=self.store.answer(99,other['id'],'rio','okay',555,now=100+ANSWER_INTERVAL);self.assertEqual(result['coins'],25)
  self.assertEqual(result['next_at'],100+2*ANSWER_INTERVAL)
 def test_correct_answer_blocks_other_modes_and_does_not_reset_at_midnight(self):
  stamp=23*3600+59*60
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'mg','first',555,now=stamp)
  other=self.store.open(99,'acertijo')
  with self.assertRaises(AnswerWait) as caught:self.store.answer(99,other['id'],'rio','after-midnight',555,now=24*3600)
  self.assertEqual(caught.exception.next_at,stamp+ANSWER_INTERVAL)
  self.assertEqual(self.eco.account(99)['balance'],25)
 def test_duplicate_submission_does_not_push_back_the_next_turn(self):
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'mg','same',555,now=100)
  self.store.answer(99,row['id'],'mg','same',555,now=1000)
  self.store.answer(99,row['id'],'mg','old-modal',555,now=2000)
  self.assertEqual(self.store.availability(99,now=2000)['next_at'],100+ANSWER_INTERVAL)
 def test_viewing_skipping_and_hints_do_not_consume_the_turn(self):
  first=self.store.open(99,'foto');self.store.get(first['id'],99)
  self.store.open(99,'foto',previous=first['id'],skip=True)
  self.assertTrue(self.store.availability(99,now=100)['available'])
 def test_concurrent_wrong_answers_only_consume_one_turn(self):
  row=self.store.open(99,'roleplay')
  def attempt(op):
   try:return self.store.answer(99,row['id'],'Wrong',op,555,now=100)['state']
   except AnswerWait:return 'blocked'
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,['first','second']))
  self.assertCountEqual(results,['wrong','blocked'])
  self.assertEqual(self.store.availability(99,now=100)['next_at'],100+ANSWER_INTERVAL)
 def test_existing_actual_answers_seed_the_timer_but_old_button_receipts_do_not(self):
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'mg','first',555,now=100)
  self.store.answer(99,row['id'],'mg','old-button',555,now=1000)
  with self.store.db() as db:db.execute('DROP TABLE lv_game_turns')
  self.store.initialize(QUESTIONS)
  self.assertEqual(self.store.availability(99,now=200)['next_at'],100+ANSWER_INTERVAL)
  self.store.initialize(QUESTIONS)
  self.assertEqual(self.store.availability(99,now=300)['next_at'],100+ANSWER_INTERVAL)
 def test_wrong_answer_wait_survives_backup_and_restore(self):
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'Wrong','first',555,now=100)
  copy=Path(self.tmp.name)/'copy.sqlite';snapshot(self.path,copy);restored=MinigameStore(copy);restored.initialize(QUESTIONS)
  with self.assertRaises(AnswerWait):restored.answer(99,row['id'],'mg','too-soon',555,now=200)
  self.assertEqual(restored.availability(99,now=200)['next_at'],100+ANSWER_INTERVAL)
 def test_different_players_have_independent_turns(self):
  first=self.store.open(99,'roleplay');second=self.store.open(100,'roleplay')
  self.store.answer(99,first['id'],'mg','first',555,now=100)
  self.assertTrue(self.store.availability(100,now=100)['available'])
  self.assertEqual(self.store.answer(100,second['id'],'mg','second',555,now=100)['coins'],25)
 def test_skip_does_not_pay_and_picks_another_unwon_question(self):
  row=self.store.open(99,'foto');other=self.store.open(99,'foto',previous=row['id'],skip=True)
  self.assertNotEqual(row['question'],other['question']);self.assertEqual(self.eco.account(99)['balance'],0)
  result=self.store.answer(99,row['id'],'Chiliad','old-form',555,now=100);self.assertEqual(result['state'],'skipped')
 def test_old_skip_button_does_not_skip_current_question(self):
  first=self.store.open(99,'foto');second=self.store.open(99,'foto',previous=first['id'],skip=True)
  again=self.store.open(99,'foto',previous=first['id'],skip=True)
  self.assertEqual(again['id'],second['id'])
 def test_restart_keeps_progress_and_the_active_question(self):
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'mg','one',555,now=100)
  current=self.store.open(99,'foto');other=MinigameStore(self.path);other.initialize(QUESTIONS)
  self.assertEqual(other.open(99,'foto')['id'],current['id']);self.assertIsNone(other.open(99,'roleplay'))
  self.assertEqual(other.progress(99)['coins'],25)
 def test_active_question_uses_its_original_answers_after_bank_changes(self):
  row=self.store.open(99,'roleplay');changed=[dict(q,answer='Otro',aliases=['Otro']) if q['id']=='rol01' else q for q in QUESTIONS]
  self.store.initialize(changed);result=self.store.answer(99,row['id'],'mg','original',555,now=100)
  self.assertEqual(result['coins'],25)
 def test_changed_question_cannot_repay_a_previous_winner(self):
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'mg','one',555,now=100)
  self.store.initialize([dict(q,aliases=['Otro']) if q['id']=='rol01' else q for q in QUESTIONS])
  self.assertIsNone(self.store.open(99,'roleplay'));self.assertEqual(self.store.progress(99)['coins'],25)
 def test_failure_after_credit_rolls_back_money_and_result_together(self):
  row=self.store.open(99,'roleplay')
  with self.store.db() as db:db.execute("CREATE TRIGGER fail_game_win BEFORE INSERT ON lv_game_wins BEGIN SELECT RAISE(ABORT,'test crash'); END")
  with self.assertRaises(sqlite3.IntegrityError):self.store.answer(99,row['id'],'mg','one',555,now=100)
  self.assertEqual(self.eco.account(99)['balance'],0);self.assertEqual(self.store.get(row['id'],99)['status'],'active')
  with self.store.db() as db:db.execute('DROP TRIGGER fail_game_win')
  self.assertEqual(self.store.answer(99,row['id'],'mg','one',555,now=100)['coins'],25)
 def test_backup_restore_preserves_payment_and_prevents_replay(self):
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'mg','one',555,now=100)
  copy=Path(self.tmp.name)/'copy.sqlite';snapshot(self.path,copy);restored=MinigameStore(copy);restored.initialize(QUESTIONS)
  result=restored.answer(99,row['id'],'mg','new-attempt',555,now=120)
  self.assertEqual(result['coins'],0);self.assertEqual(EconomyStore(copy).account(99)['balance'],25)
 def test_ranking_counts_wins_instead_of_spending_balance(self):
  row=self.store.open(99,'roleplay');self.store.answer(99,row['id'],'mg','one',555,now=100)
  self.eco.adjust(99,-10,'Prueba de compra',555,'spend')
  self.assertEqual(self.store.ranking()[0]['coins'],25);self.assertEqual(self.store.progress(99)['balance'],15)
 def test_prefixes_accents_and_case_are_accepted_but_substrings_are_not(self):
  self.assertEqual(normalize('Creo que es el MUELLE DE DEL PERRO!'),normalize('Muelle de Del Perro'))
  self.assertEqual(normalize('ES UN RÍO'),normalize('Un río'))
  self.assertNotEqual(normalize('No es metagaming'),normalize('Metagaming'))
 def test_bank_has_50_distinct_photos_and_no_duplicate_ids(self):
  bank=load_bank();photos=[q for q in bank if q['kind']=='foto']
  self.assertEqual(len(photos),50);self.assertEqual(len({q['image'] for q in photos}),50)
  self.assertEqual(len(bank),100);self.assertEqual(len({q['id'] for q in bank}),100)
  self.assertTrue(all(len(q['prompt'])<2000 and q['answer'] in q['aliases'] for q in bank))

class GameUiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
  with closing(sqlite3.connect(self.path)) as db:db.executescript(SCHEMA)
  self.guild=NS(id=55,fetch_member=AsyncMock(return_value=NS(id=99)))
  self.bot=NS(user=NS(id=555),get_guild=lambda gid:self.guild if gid==55 else None);self.system=MinigameSystem(self.bot,self.path,55)
  await self.system.call('initialize',QUESTIONS)
 async def asyncTearDown(self):self.tmp.cleanup()
 async def test_controls_survive_restart_and_form_fits_discord(self):
  self.assertTrue(GamePanel(self.system).is_persistent());self.assertTrue(controls('a'*24,['answer','hint','skip']).is_persistent())
  modal=AnswerForm(self.system,'a'*24);self.assertLessEqual(len(modal.children[0].label),45)
  self.assertEqual(modal.children[0].max_length,150)
 async def test_wrong_server_channel_or_bot_cannot_play(self):
  for guild,channel,bot in [(56,GENERAL,False),(55,123,False),(55,GENERAL,True)]:
   with self.assertRaises(ValueError):await self.system.member(NS(guild_id=guild,channel_id=channel,user=NS(id=99,bot=bot)))
 async def test_correct_answer_has_no_public_reply(self):
  row=await self.system.call('open',99,'roleplay');self.system.member=AsyncMock()
  i=NS(user=NS(id=99),id=1,response=NS(is_done=lambda:True),followup=NS(send=AsyncMock()))
  await self.system.answer(i,row['id'],'MG')
  i.followup.send.assert_awaited_once();self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
  self.assertEqual(i.followup.send.call_args.kwargs['allowed_mentions'].to_dict(),discord.AllowedMentions.none().to_dict())
 async def test_forged_hint_does_not_reveal_someone_elses_question(self):
  row=await self.system.call('open',99,'roleplay');self.system.member=AsyncMock()
  i=NS(user=NS(id=100),response=NS(defer=AsyncMock()))
  with self.assertRaises(ValueError):await self.system.action(i,row['id'],'hint')
 async def test_answer_button_shows_countdown_instead_of_opening_another_form(self):
  row=await self.system.call('open',99,'roleplay');await self.system.call('answer',99,row['id'],'Wrong','first',555)
  self.system.member=AsyncMock()
  i=NS(guild_id=55,channel_id=GENERAL,user=NS(id=99,bot=False),response=NS(defer=AsyncMock(),send_modal=AsyncMock()))
  with patch('minigames.reply',new=AsyncMock()) as send:await self.system.action(i,row['id'],'answer')
  i.response.send_modal.assert_not_awaited();self.assertIn('Próximo turno',send.call_args.args[1])
 async def test_answer_button_opens_its_modal_without_waiting_for_discord_member_lookup(self):
  row=await self.system.call('open',99,'roleplay')
  self.guild.fetch_member.side_effect=AssertionError('Opening the modal must not wait for the Discord API')
  i=NS(guild_id=55,channel_id=GENERAL,user=NS(id=99,bot=False),response=NS(send_modal=AsyncMock()))
  await self.system.action(i,row['id'],'answer')
  i.response.send_modal.assert_awaited_once();self.guild.fetch_member.assert_not_awaited()
  form=i.response.send_modal.call_args.args[0]
  self.assertIsInstance(form,AnswerForm);self.assertEqual(form.token,row['id'])
 async def test_answer_modal_cannot_be_opened_for_someone_elses_question(self):
  row=await self.system.call('open',99,'roleplay')
  i=NS(guild_id=55,channel_id=GENERAL,user=NS(id=100,bot=False),response=NS(send_modal=AsyncMock()))
  with self.assertRaises(ValueError):await self.system.action(i,row['id'],'answer')
  i.response.send_modal.assert_not_awaited()
 async def test_answer_submission_still_checks_membership_before_awarding_coins(self):
  row=await self.system.call('open',99,'roleplay')
  self.guild.fetch_member.side_effect=discord.NotFound(NS(status=404,reason='Not Found'),'Unknown Member')
  i=NS(id=1,guild_id=55,channel_id=GENERAL,user=NS(id=99,bot=False))
  with self.assertRaisesRegex(ValueError,'La Venganza RP'):await self.system.answer(i,row['id'],'MG')
  self.guild.fetch_member.assert_awaited_once_with(99)
  self.assertEqual((await self.system.call('get',row['id'],99))['status'],'active')
  self.assertEqual(EconomyStore(self.path).account(99)['balance'],0)
 async def test_photo_is_bound_inside_embed_with_no_duplicate_content(self):
  question=next(q for q in load_bank() if q['id']=='foto01')
  row={'id':'a'*24,'payload':json.dumps(question)}
  with patch('minigames.reply',new=AsyncMock()) as send:
   await self.system.show_question(NS(),row)
  kwargs=send.call_args.kwargs
  self.assertEqual(kwargs['embed'].image.url,'attachment://reto.png');self.assertEqual(kwargs['file'].filename,'reto.png')
  self.assertNotIn(question['answer'],kwargs['embed'].description);kwargs['file'].close()
