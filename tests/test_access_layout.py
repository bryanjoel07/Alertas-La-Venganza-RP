import unittest
from types import SimpleNamespace
import discord
from access_layout import (access_changes,merged_raw,positions_for,ROLE_ORDER,STAFF,ADMINS,
                           CATEGORY_ROLES,COMMANDS,GANGS,POLICE,CITIZENS)

class Role:
    def __init__(self,rid,position,managed=False):
        self.id,self.position,self.managed=rid,position,managed
    def __ge__(self,other):
        return self.position>=other.position

class AccessLayoutTests(unittest.TestCase):
    def test_raw_merge_preserves_uncached_member_and_unrelated_denies(self):
        allow=discord.Permissions.none();allow.attach_files=True
        deny=discord.Permissions.none();deny.send_messages=True
        channel=SimpleNamespace(_overwrites=[SimpleNamespace(type=1,id=123,allow=16,deny=32),
            SimpleNamespace(type=0,id=456,allow=allow.value,deny=deny.value)])
        output=merged_raw(channel,{456:dict(view_channel=True)})
        self.assertIn(dict(id='123',type=1,allow='16',deny='32'),output)
        target=next(o for o in output if o['id']=='456')
        self.assertTrue(discord.Permissions(int(target['allow'])).attach_files)
        self.assertTrue(discord.Permissions(int(target['deny'])).send_messages)
        self.assertTrue(discord.Permissions(int(target['allow'])).view_channel)

    def test_categories_and_children_keep_staff_and_own_access(self):
        for cat,own in CATEGORY_ROLES.items():
            for channel in (SimpleNamespace(id=cat,category_id=None),SimpleNamespace(id=999,category_id=cat)):
                changes=access_changes(channel,111)
                for rid in STAFF|own:
                    self.assertTrue(changes[rid]['view_channel'])
                # Existing read-only documentation and Citizen writing permissions are untouched.
                self.assertNotIn('send_messages',changes[CITIZENS])
                for rid in own:
                    self.assertNotIn('send_messages',changes[rid])
        for cat in (1567257821911720027,1567225971306926090,1561151256670511267,1567081958180261949,1541628457216249918):
            changes=access_changes(SimpleNamespace(id=cat,category_id=None),111)
            for rid in (GANGS|POLICE)-CATEGORY_ROLES[cat]:
                self.assertFalse(changes[rid]['view_channel'])

    def test_commands_staff_read_and_admin_execution(self):
        for cid,(_,admin,_) in COMMANDS.items():
            changes=access_changes(SimpleNamespace(id=cid,category_id=1515887247227093084),111)
            for rid in STAFF:
                self.assertTrue(changes[rid]['view_channel'])
                self.assertEqual(changes[rid]['use_application_commands'],not admin or rid in ADMINS)
                self.assertEqual(changes[rid]['send_messages'],not admin or rid in ADMINS)
        self.assertEqual(access_changes(SimpleNamespace(id=1513422142014754976,category_id=1513422023626326257),111),{})

    def test_role_order_reuses_slots_and_excludes_anchors(self):
        roles=[Role(rid,16+i) for i,rid in enumerate(reversed(ROLE_ORDER))]
        managed=Role(999,5,True);staff=Role(888,45)
        output=positions_for(roles+[managed,staff],Role(777,40))
        self.assertNotIn(managed,output);self.assertNotIn(staff,output)
        self.assertEqual(sorted(output.values()),list(range(16,40)))
        by_id={r.id:p for r,p in output.items()}
        self.assertEqual([by_id[rid] for rid in ROLE_ORDER],list(range(16,40)))
        roles[0].managed=True
        with self.assertRaises(ValueError):positions_for(roles,Role(777,40))
        with self.assertRaises(ValueError):positions_for(roles[1:],Role(777,40))
