import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,AsyncMock
import discord
from ticket_forms import FORMS,submission
from tickets_ui import OpenForm,PurchasePicker,DepartmentPicker
from tickets_store import DEPARTMENTS

class TicketFormTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.system=MagicMock();self.system.open=AsyncMock()
  self.i=MagicMock(user=SimpleNamespace(id=123456789012345678))
  self.i.response.is_done.return_value=False
  self.i.response.defer=AsyncMock();self.i.response.send_message=AsyncMock();self.i.response.send_modal=AsyncMock()
  self.i.followup.send=AsyncMock()
 def fill(self,form,values):
  for key,value in values.items():form.inputs[key]._value=value
 async def test_each_topic_has_its_own_complete_modal_with_valid_discord_payload(self):
  self.assertEqual(set(FORMS),set(DEPARTMENTS))
  sequences=set()
  for department,questions in FORMS.items():
   modal=OpenForm(self.system,department)
   data=modal.to_dict();components=[r['components'][0] for r in data['components']]
   self.assertLessEqual(len(components),5)
   self.assertEqual([c['label'] for c in components],[q.label for q in questions])
   self.assertTrue(all(len(c['label'])<=45 and c['max_length']<=1000 for c in components))
   sequences.add(tuple(q.label for q in questions))
   self.assertNotIn('Asunto',[c['label'] for c in components])
  self.assertEqual(len(sequences),len(FORMS))
 async def test_donation_answers_keep_their_meaning_and_do_not_require_a_payment_format(self):
  form=OpenForm(self.system,'donacion')
  answers={'type':' Algo para el server ','what':'Quiero ayudar con los gastos del server','how_much':'Todavía no sé cuánto','how':'Díganme cómo puedo hacerlo','extra':'  '}
  self.fill(form,answers);await form.on_submit(self.i)
  args=self.system.open.await_args.args
  self.assertEqual(args[1],'donacion');self.assertEqual(args[2],'Donación: Algo para el server')
  self.assertEqual(args[3],{q.label:answers[q.key].strip() for q in FORMS['donacion'] if answers[q.key].strip()})
  self.assertIsNone(args[4]);self.assertIsNone(args[5])
 async def test_report_keeps_discord_exclusion_and_rejects_self_or_bad_id(self):
  answers={'person':'Jugador 7','what':'Me chocó a propósito','when':'Hoy en la plaza','proof':'Tengo un video','discord_id':'234567890123456789'}
  subject,form,excluded=submission('jugador',answers,self.i.user.id)
  self.assertEqual(excluded,234567890123456789);self.assertIn('Jugador 7',subject)
  self.assertEqual(form['¿Qué pasó?'],'Me chocó a propósito')
  for value in ('123','no tengo',str(self.i.user.id)):
   with self.assertRaises(ValueError):submission('jugador',dict(answers,discord_id=value),self.i.user.id)
  self.assertIsNone(submission('jugador',dict(answers,discord_id=''),self.i.user.id)[2])
 async def test_required_whitespace_answers_never_open_a_ticket(self):
  form=OpenForm(self.system,'soporte')
  self.fill(form,{'help':'  ','problem':'No abre','since':'Hoy'})
  await form.on_submit(self.i)
  self.system.open.assert_not_awaited()
  self.assertIn('Te falta responder',self.i.response.send_message.call_args.args[0])
 async def test_shop_preserves_selected_receipt_and_prefills_product_name(self):
  picker=PurchasePicker(self.system,[dict(id='own-purchase',name='Rojo Venganza',price=300,status='delivered')])
  picker._values=['own-purchase'];await picker.callback(self.i)
  form=self.i.response.send_modal.call_args.args[0]
  self.assertEqual(form.inputs['item'].default,'Rojo Venganza')
  self.fill(form,dict(item='Rojo Venganza',problem='No veo el color',received='Compré el color y sigo igual',when='Hoy',proof=''))
  await form.on_submit(self.i)
  self.assertEqual(self.system.open.await_args.args[5],'own-purchase')
 async def test_department_picker_opens_the_specific_form_without_buying_anything(self):
  picker=DepartmentPicker(self.system)
  for department in ('donacion','soporte','jugador','apelacion','faccion','staff'):
   picker._values=[department];await picker.callback(self.i)
   modal=self.i.response.send_modal.call_args.args[0]
   self.assertEqual(set(modal.inputs),{q.key for q in FORMS[department]})
  self.system.open.assert_not_awaited()
