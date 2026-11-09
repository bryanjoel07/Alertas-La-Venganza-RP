import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
from economy_delivery import Delivery

class Role:
    def __init__(self,rid,position,color=0):
        self.id,self.position=rid,position
        self.color=discord.Color(color)
    def __ge__(self,other):return self.position>=other.position

class CosmeticHierarchyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.botrole=Role(1,40)
        self.staffrole=Role(1245008186440683530,48,0xFF0000)
        self.member=SimpleNamespace(id=10,roles=[self.staffrole],top_role=self.staffrole,
            guild=SimpleNamespace(owner_id=10,me=SimpleNamespace(top_role=self.botrole,
                guild_permissions=discord.Permissions(manage_roles=True,manage_nicknames=True))))
        self.delivery=Delivery(MagicMock())

    async def test_owner_and_higher_staff_can_receive_only_the_decorative_role(self):
        self.delivery.preflight(self.member,'title')
        store=self.delivery.store
        store.equipped.return_value=[dict(slot='titulo',value='Leyenda')]
        store.rows.return_value=[]
        store.config.return_value=''
        cosmetic=Role(50,39)
        self.delivery.role=AsyncMock(return_value=cosmetic)
        self.member.add_roles=AsyncMock()
        self.member.remove_roles=AsyncMock()
        await self.delivery.sync_member(self.member)
        self.member.add_roles.assert_awaited_once_with(cosmetic,reason='Cosmético equipado')
        self.member.remove_roles.assert_not_awaited()
        self.assertEqual(self.member.roles,[self.staffrole])

    async def test_missing_manage_roles_still_blocks(self):
        self.member.guild.me.guild_permissions.manage_roles=False
        with self.assertRaisesRegex(ValueError,'Gestionar roles'):
            self.delivery.preflight(self.member,'title')

    async def test_staff_color_and_owner_nickname_still_block(self):
        with self.assertRaisesRegex(ValueError,'color'):
            self.delivery.preflight(self.member,'color')
        with self.assertRaisesRegex(ValueError,'apodo'):
            self.delivery.preflight(self.member,'nickname')

    async def test_existing_role_above_bot_still_rejected(self):
        role=Role(50,45)
        role.permissions=discord.Permissions.none();role.managed=False;role.mentionable=False
        self.delivery.store.resource.return_value=dict(resource_id=50)
        self.member.guild.get_role=lambda rid:role
        with self.assertRaisesRegex(ValueError,'jerarquía'):
            await self.delivery.role(self.member.guild,'titulo','Leyenda')
