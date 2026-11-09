import unittest
from navigation import key,plan,protected_state


def channel(id,name,kind='text',parent=None,position=0,bucket=0):
    return dict(id=str(id),name=name,type=kind,parent=str(parent) if parent else None,
                position=position,bucket=bucket,overwrites=[('everyone',0,1024)])


class NavigationTests(unittest.TestCase):
    def test_styled_accents_and_emoji_match_existing_names(self):
        self.assertEqual(key('│・🚨┊ 𝐈𝐧𝐟𝐨𝐫𝐦𝐚𝐜𝐢𝐨́𝐧'),'informacion')
        self.assertEqual(key('│・ ⚫┊ 𝐄𝐥 𝐂𝐚𝐥𝐞𝐧𝐭𝐨́𝐧'),'elcalenton')

    def test_new_player_order_and_main_channel_order_without_moving_parents(self):
        channels=[channel(1,'│・👑┊ 𝐋𝐚 𝐕𝐞𝐧𝐠𝐚𝐧𝐳𝐚 𝐑𝐏','category',position=0,bucket=4),
                  channel(2,'│・🚨┊ 𝐈𝐧𝐟𝐨𝐫𝐦𝐚𝐜𝐢𝐨́𝐧','category',position=1,bucket=4),
                  channel(3,'│・✈️┊ 𝐋𝐥𝐞𝐠𝐚𝐧𝐝𝐨','category',position=2,bucket=4),
                  channel(4,'🔴┊𝐆𝐞𝐧𝐞𝐫𝐚𝐥',parent=1,position=0),
                  channel(5,'📖┊𝐆𝐮𝐢𝐚-𝐃𝐞𝐥-𝐁𝐨𝐭',parent=1,position=3),
                  channel(6,'👤┊𝐏𝐞𝐫𝐟𝐢𝐥𝐞𝐬',parent=1,position=2),
                  channel(7,'⚜️┊𝐂𝐨𝐧𝐧𝐞𝐜𝐭',parent=2,position=1)]
        before=protected_state(channels)
        payload=plan(channels)
        positions={c['id']:c['position'] for c in payload}
        self.assertLess(positions['3'],positions['2'])
        self.assertLess(positions['2'],positions['1'])
        self.assertLess(positions['5'],positions['4'])
        self.assertLess(positions['4'],positions['6'])
        self.assertEqual(protected_state(channels),before)
        self.assertEqual({c['id'] for c in payload},{c['id'] for c in channels})
        for item in payload:
            self.assertEqual(set(item),{'id','position'})

    def test_unknown_channels_keep_relative_order_in_their_category(self):
        channels=[channel(1,'La Venganza RP','category',bucket=4),
                  channel(2,'Otro canal A',parent=1,position=7),channel(3,'Otro canal B',parent=1,position=8),
                  channel(4,'General',parent=1,position=10),channel(5,'Privado',parent=1,position=0,bucket=2,kind='voice')]
        result={c['id']:c['position'] for c in plan(channels)}
        self.assertLess(result['4'],result['2'])
        self.assertLess(result['2'],result['3'])
        self.assertEqual(result['5'],0)

    def test_opening_server_is_first_and_closing_logs_is_last_even_with_unknown_category(self):
        categories=[channel(1,'│・✈️┊ 𝐋𝐥𝐞𝐠𝐚𝐧𝐝𝐨','category',position=0,bucket=4),
                    channel(2,'╭・🗄️┊ SERVER','category',position=16,bucket=4),
                    channel(3,'╰・📁 ┊ 𝐋𝐨𝐠𝐬','category',position=17,bucket=4),
                    channel(4,'Otra categoría','category',position=18,bucket=4)]
        ordered=sorted(plan(categories),key=lambda c:c['position'])
        self.assertEqual(ordered[0]['id'],'2')
        self.assertEqual(ordered[-1]['id'],'3')

    def test_actual_regroup_preserves_channel_overwrites_and_required_main_channels(self):
        from navigation import REGROUP,regroup
        categories=[channel(1,'Llegando','category',bucket=4),channel(2,'Logs','category',bucket=4),
                    channel(3,'Staff','category',bucket=4),channel(4,'La Venganza RP','category',bucket=4)]
        items=categories+[channel(id,'Canal',parent=4) for id in REGROUP]
        items += [channel('1569151200673140897','Perfiles',parent=4),
                  channel('1569084821983076512','Tienda Exclusive',parent=4)]
        before=protected_state(items)
        projected,moves=regroup(items)
        self.assertEqual(len(moves),7)
        category_ids={'llegando':'1','logs':'2','staff':'3'}
        for item in projected:
            if item['id'] in REGROUP:
                self.assertEqual(item['parent'],category_ids[REGROUP[item['id']]])
            self.assertEqual(item['overwrites'],next(c['overwrites'] for c in items if c['id']==item['id']))
        for id in ('1569151200673140897','1569084821983076512'):
            self.assertEqual(next(c['parent'] for c in projected if c['id']==id),'4')
        self.assertEqual(protected_state(items),before)


class DiscordMoveTests(unittest.IsolatedAsyncioTestCase):
    async def test_discord_parent_change_limit_and_permission_preservation(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from navigation import apply_layout
        moved=[]
        async def api(guild_id,payload,**kwargs):
            parent_changes=[c for c in payload if 'parent_id' in c]
            if len(parent_changes)>1:
                raise ValueError('Discord 40009: Only one parent_id modified at a time')
            for item in parent_changes:
                self.assertFalse(item['lock_permissions'])
                self.assertNotIn('permission_overwrites',item)
                moved.append(item['id'])
        http=SimpleNamespace(bulk_channel_update=AsyncMock(side_effect=api))
        await apply_layout(http,123,[dict(id='1',position=0),
            dict(id='2',position=1,parent_id='10',lock_permissions=False),
            dict(id='3',position=2,parent_id='11',lock_permissions=False)])
        self.assertEqual(moved,['2','3'])

    async def test_one_private_channel_does_not_block_other_moves(self):
        import discord
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from navigation import apply_layout
        changed=[]
        async def api(guild_id,payload,**kwargs):
            for item in payload:
                if 'parent_id' in item:
                    if item['id']=='2':
                        raise discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),{'code':50001,'message':'Missing Access'})
                    changed.append(item['id'])
        http=SimpleNamespace(bulk_channel_update=AsyncMock(side_effect=api))
        blocked=await apply_layout(http,123,[dict(id='1',position=0),
            dict(id='2',position=1,parent_id='10',lock_permissions=False),
            dict(id='3',position=2,parent_id='11',lock_permissions=False)])
        self.assertEqual(blocked,['2'])
        self.assertEqual(changed,['3'])


class FullOrganizationTests(unittest.TestCase):
    def test_multimedia_groups_six_channels_and_keeps_profiles_and_shop(self):
        from navigation import REGROUP,MEDIA_CHANNELS,regroup
        categories=[channel(1,'Llegando','category',bucket=4),channel(2,'Logs','category',bucket=4),
                    channel(3,'Staff','category',bucket=4),channel(4,'La Venganza RP','category',bucket=4),
                    channel(5,'│・ 🎬┊ 𝐌𝐮𝐥𝐭𝐢𝐦𝐞𝐝𝐢𝐚','category',bucket=4)]
        items=categories+[channel(id,'Canal',parent=4) for id in {**REGROUP,**MEDIA_CHANNELS}]
        items += [channel('1569151200673140897','Perfiles',parent=4),channel('1569084821983076512','Tienda',parent=4)]
        projected,moves=regroup(items,include_media=True)
        self.assertEqual(len(moves),13)
        for item in projected:
            if item['id'] in MEDIA_CHANNELS:
                self.assertEqual(item['parent'],'5')
            if item['id'] in ('1569151200673140897','1569084821983076512'):
                self.assertEqual(item['parent'],'4')
            self.assertEqual(item['overwrites'],next(c['overwrites'] for c in items if c['id']==item['id']))

    def test_style_is_idempotent_and_preserves_open_ticket_names(self):
        from types import SimpleNamespace
        from navigation import styled_channel_name
        for name in ('🛡️┊𝐒𝐚𝐧𝐜𝐢𝐨𝐧𝐞𝐬','🔊┊𝐏𝐮𝐛𝐥𝐢𝐜𝐨 𝟏','no-cerrar-donacion','incumplimiento-de-normativas'):
            obj=SimpleNamespace(id=123,type='text',name=name)
            self.assertEqual(styled_channel_name(obj),name)
        category=SimpleNamespace(id=1,type='category',name='╭・ 🗄️┊ SERVER')
        self.assertEqual(styled_channel_name(category),category.name)

    def test_legacy_small_caps_get_same_bold_style_as_other_channels(self):
        import unicodedata
        from types import SimpleNamespace
        from navigation import styled_channel_name
        obj=SimpleNamespace(id=1425183472150118631,type='news',name='📢┊ᴜᴘᴅᴀᴛᴇs-ᴇꜰʟꜱ')
        result=styled_channel_name(obj)
        self.assertEqual(unicodedata.normalize('NFKC',result),'📢┊Updates-EFLS')
        self.assertIn('𝐔',result)
