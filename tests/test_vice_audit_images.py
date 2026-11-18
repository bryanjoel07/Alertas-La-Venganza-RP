"""Authentic comparison reports: scoped inputs, bounded fetches and durable files."""
import hashlib
import io
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from PIL import Image

import vice_audit_images as visuals
from vice_design import GUILD_ID


OLD, NEW = '1' * 32, '2' * 32
EVENT = 1572718032730464406


def png(color='red', size=(300, 150)):
    result = io.BytesIO()
    Image.new('RGB', size, color).save(result, format='PNG')
    return result.getvalue()


def entry(**kwargs):
    values = dict(id=EVENT, guild=NS(id=GUILD_ID), target=NS(id=GUILD_ID),
                  action=discord.AuditLogAction.guild_update,
                  before={'icon_hash': OLD}, after={'icon_hash': NEW})
    values.update(kwargs)
    return NS(**values)


def api_entry():
    guild = NS(id=GUILD_ID, _state=None, get_member=lambda _: None)
    return discord.AuditLogEntry(
        users={}, integrations={}, app_commands={}, automod_rules={}, webhooks={},
        guild=guild, data=dict(id=str(EVENT), action_type=1, target_id=str(GUILD_ID),
                               user_id=None, changes=[dict(key='icon_hash', old_value=OLD,
                                                         new_value='a_' + NEW)]))


def embed(filename):
    return discord.Embed().set_image(url='attachment://' + filename)


class ImagePlanTests(unittest.TestCase):
    def test_real_discord_assets_become_exact_canonical_urls(self):
        plan = visuals.image_plan(api_entry())
        self.assertEqual(plan, dict(event_id=str(EVENT), rows=[dict(
            kind='icon', before=f'https://cdn.discordapp.com/icons/{GUILD_ID}/{OLD}.png?size=1024',
            after=f'https://cdn.discordapp.com/icons/{GUILD_ID}/a_{NEW}.png?size=1024')]))

    def test_wrong_guild_action_target_or_unchanged_assets_have_no_plan(self):
        for source in (entry(guild=NS(id=123)), entry(target=NS(id=123)),
                       entry(action=discord.AuditLogAction.channel_update),
                       entry(after={'icon_hash': OLD}),
                       entry(before={'name': 'A'}, after={'name': 'B'})):
            with self.subTest(source=source):
                self.assertIsNone(visuals.image_plan(source))

    def test_arbitrary_urls_and_malformed_hashes_cannot_be_fetched(self):
        for value in ('https://example.com/a.png', '../secrets', '0' * 31,
                      'a_' + 'F' * 32, NS(url='https://example.com/a.png')):
            plan = visuals.image_plan(entry(after={'icon_hash': value}))
            self.assertEqual(plan['rows'][0]['after'], 'unavailable')

    def test_attachment_url_parser_rejects_untrusted_sources(self):
        name = f'vice-audit-{EVENT}-' + 'a' * 24 + '.png'
        for url in ('attachment://' + name,
                    f'https://cdn.discordapp.com/attachments/123/456/{name}?ex=abc',
                    f'https://media.discordapp.net/attachments/123/456/{name}?width=900'):
            self.assertEqual(visuals.attachment_filename(url), name)
        for url in ('https://example.com/attachments/123/456/' + name,
                    'attachment://../' + name,
                    'https://cdn.discordapp.com/icons/123/' + name,
                    'https://user@cdn.discordapp.com/attachments/123/456/' + name,
                    'https://[invalid/attachments/123/456/' + name,
                    None):
            self.assertIsNone(visuals.attachment_filename(url))


class RendererTests(unittest.TestCase):
    def test_wide_and_tall_images_fit_without_cropping(self):
        wide = Image.new('RGB', (800, 100), 'red')
        wide.putpixel((0, 50), (0, 255, 0))
        source = io.BytesIO()
        wide.save(source, format='PNG')
        data = visuals.render_comparison(dict(rows=[dict(kind='banner', before='wide', after='tall')]),
                                         {'wide': source.getvalue(), 'tall': png('blue', (100, 800))})
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, (900, 312))
        # Wide art is letterboxed vertically; portrait art is letterboxed horizontally.
        self.assertEqual(image.getpixel((200, 185)), (255, 0, 0))
        self.assertEqual(image.getpixel((200, 100)), (20, 21, 26))
        self.assertEqual(image.getpixel((670, 90)), (0, 0, 255))
        self.assertEqual(image.getpixel((470, 185)), (20, 21, 26))

    def test_three_changed_assets_have_three_bounded_rows(self):
        plan = dict(rows=[dict(kind=kind, before=None, after='new') for kind in visuals.FIELDS])
        data = visuals.render_comparison(plan, {'new': png()})
        self.assertEqual(Image.open(io.BytesIO(data)).size, (900, 936))
        self.assertLess(len(data), visuals.MAX_BYTES)

    def test_none_removal_and_unavailable_have_distinct_labels(self):
        labels = []
        original = visuals.ImageDraw.ImageDraw.text
        def recording(draw, xy, text, *args, **kwargs):
            labels.append(text)
            return original(draw, xy, text, *args, **kwargs)
        plan = dict(rows=[dict(kind='icon', before=None, after='missing'),
                          dict(kind='banner', before='missing', after=None)])
        with patch.object(visuals.ImageDraw.ImageDraw, 'text', recording):
            visuals.render_comparison(plan, {})
        self.assertIn('Sin imagen', labels)
        self.assertIn('Imagen retirada', labels)
        self.assertEqual(labels.count('Imagen no disponible'), 2)

    def test_decode_limits_and_animation_uses_first_frame(self):
        gif = io.BytesIO()
        Image.new('RGB', (10, 10), 'red').save(gif, format='GIF', save_all=True,
            append_images=[Image.new('RGB', (10, 10), 'blue')], duration=50, loop=0)
        self.assertEqual(visuals._image(gif.getvalue()).getpixel((5, 5)), (255, 0, 0, 255))
        with self.assertRaises(ValueError):
            visuals._image(b'a' * (visuals.MAX_BYTES + 1))
        with patch.object(visuals, 'MAX_PIXELS', 100):
            with self.assertRaises(ValueError):
                visuals._image(png(size=(11, 10)))

    def test_authentic_seed_is_exact_field_guild_hash_and_digest(self):
        image_hash = next(iter(visuals.SEEDS))
        url = f'https://cdn.discordapp.com/splashes/{GUILD_ID}/{image_hash}.png?size=1024'
        data = visuals._seed(url)
        self.assertIsNotNone(data)
        self.assertEqual(hashlib.sha256(data).hexdigest(), visuals.SEEDS[image_hash])
        self.assertIsNone(visuals._seed(url.replace('/splashes/', '/icons/')))
        self.assertIsNone(visuals._seed(url.replace(str(GUILD_ID), '123')))
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / (image_hash + '.jpg')).write_bytes(png())
            with patch.object(visuals, 'SEED_DIR', Path(directory)):
                self.assertIsNone(visuals._seed(url))


class DurableVisualTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'audit.sqlite3'
        self.renderer = visuals.AuditVisuals(self.path)
        await self.renderer.start()

    async def test_wrong_scope_and_unsafe_hash_never_hit_network(self):
        self.renderer._download = AsyncMock(return_value=None)
        self.assertIsNone(await self.renderer.render(entry(guild=NS(id=123))))
        name = await self.renderer.render(entry(before={'icon_hash': None},
                                               after={'icon_hash': 'https://internal.local/private'}))
        self.assertTrue(name.startswith('vice-audit-'))
        self.renderer._download.assert_not_awaited()

    async def test_success_survives_restart_and_files_are_exact_and_deduplicated(self):
        self.renderer._download = AsyncMock(return_value=png())
        name = await self.renderer.render(entry())
        self.assertEqual(self.renderer._download.await_count, 2)
        files = await self.renderer.files_for([embed(name), embed(name)])
        self.assertEqual(len(files), 1)
        data = files[0].fp.read()
        self.assertIn(hashlib.sha256(data).hexdigest()[:24], name)
        self.assertEqual(Image.open(io.BytesIO(data)).size, (900, 312))
        files[0].close()
        restarted = visuals.AuditVisuals(self.path)
        await restarted.start()
        restarted._download = AsyncMock(side_effect=AssertionError('A cached image was downloaded again'))
        self.assertEqual(await restarted.render(entry()), name)
        returned = embed(name)
        returned.set_image(url=f'https://cdn.discordapp.com/attachments/123/456/{name}?ex=abc')
        recovered = await restarted.files_for([returned])
        self.assertEqual(recovered[0].fp.read(), data)
        recovered[0].close()
        self.assertTrue(await restarted.validate_attachments(
            [NS(filename=name, size=len(data))], [dict(key=f'audit:{EVENT}')]))

    async def test_retry_only_unavailable_assets_and_retain_prior_generation(self):
        async def first(url):
            return png('red') if OLD in url else None
        self.renderer._download = AsyncMock(side_effect=first)
        with patch.object(visuals.time, 'time', return_value=1000):
            old_name = await self.renderer.render(entry())
        with patch.object(visuals.time, 'time', return_value=1000 + visuals.RETRY_SECONDS - 1):
            self.assertEqual(await self.renderer.render(entry()), old_name)
        self.assertEqual(self.renderer._download.await_count, 2)
        self.renderer._download = AsyncMock(return_value=png('blue'))
        with patch.object(visuals.time, 'time', return_value=1000 + visuals.RETRY_SECONDS):
            new_name = await self.renderer.render(entry())
        self.assertNotEqual(old_name, new_name)
        self.assertEqual(self.renderer._download.await_count, 1)
        self.assertIn(NEW, self.renderer._download.await_args.args[0])
        for name in (old_name, new_name):
            files = await self.renderer.files_for([embed(name)])
            self.assertTrue(await self.renderer.validate_attachments(
                [NS(filename=name, size=len(files[0].fp.getvalue()))], [dict(key=f'audit:{EVENT}')]))
            files[0].close()

    async def test_registered_attachment_must_belong_to_source_and_match_size(self):
        self.renderer._download = AsyncMock(return_value=png())
        name = await self.renderer.render(entry())
        attachment = NS(filename=name)
        self.assertFalse(await self.renderer.validate_attachments([attachment], [dict(key='audit:999')]))
        self.assertFalse(await self.renderer.validate_attachments(
            [attachment], [dict(key=f'audit:{EVENT}', source_id='999')]))
        self.assertFalse(await self.renderer.validate_attachments(
            [NS(filename=name, size=1)], [dict(key=f'audit:{EVENT}')]))
        self.assertFalse(await self.renderer.validate_attachments(
            [attachment, attachment], [dict(key=f'audit:{EVENT}')]))
        self.assertFalse(await self.renderer.validate_attachments(
            [NS(filename='unknown.png')], [dict(key=f'audit:{EVENT}')]))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE vice_audit_visual_files SET payload=? WHERE filename=?', (b'tampered', name))
        with self.assertRaises(ValueError):
            await self.renderer.files_for([embed(name)])
        self.assertFalse(await self.renderer.validate_attachments([attachment], [dict(key=f'audit:{EVENT}')]))

    async def test_seed_lookup_avoids_fetch_for_deleted_cdn_original(self):
        image_hash = next(iter(visuals.SEEDS))
        self.renderer._download = AsyncMock(return_value=png())
        await self.renderer.render(entry(before={'splash_hash': image_hash}, after={'splash_hash': NEW}))
        self.assertEqual(self.renderer._download.await_count, 1)
        self.assertIn(NEW, self.renderer._download.await_args.args[0])

    async def test_download_is_bounded_and_never_follows_redirects(self):
        class Response:
            def __init__(self, chunks, status=200, content_length=None):
                self.status, self.content_length = status, content_length
                self.headers = {'Content-Type': 'image/png'}
                self.content = self
                self.chunks = chunks
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def iter_chunked(self, size):
                for chunk in self.chunks:
                    yield chunk
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock()
        factory = MagicMock(return_value=session)
        url = visuals.image_plan(entry())['rows'][0]['after']
        for response in (Response([], status=302), Response([], content_length=visuals.MAX_BYTES + 1),
                         Response([b'a' * visuals.MAX_BYTES, b'b']), Response([b'not an image'])):
            session.get.return_value = response
            with patch.object(visuals.aiohttp, 'ClientSession', factory):
                self.assertIsNone(await self.renderer._download(url))
        session.get.return_value = Response([png()])
        with patch.object(visuals.aiohttp, 'ClientSession', factory):
            self.assertEqual(await self.renderer._download(url), png())
        session.get.assert_called_with(url, allow_redirects=False)
        self.assertEqual(factory.call_args.kwargs['timeout'].total, 8)


if __name__ == '__main__':
    unittest.main()
