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
