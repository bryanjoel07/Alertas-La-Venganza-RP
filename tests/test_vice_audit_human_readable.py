"""Server audit cards explain the setting, including real discord.py asset diffs."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace as NS
import unittest

import discord

from vice_audit_format import format_audit_entry


GUILD = 1572462544302383164
ACTOR = 1509288420852109383
WHEN = datetime(2026, 11, 18, 21, tzinfo=timezone.utc)
OLD_HASH = '1662ee4c26262cd955e7a7ab14362d59'
NEW_HASH = 'cb9b1d9b5053372284ee0869ba0b62e9'


def user():
    return NS(id=ACTOR, name='esschino', display_name='esschino',
              display_avatar=NS(url=f'https://cdn.discordapp.com/avatars/{ACTOR}/avatar.png'))


def entry(before=None, after=None, **kwargs):
    values = dict(id=1572718032730464406, action=discord.AuditLogAction.guild_update,
                  user=user(), user_id=ACTOR, target=NS(id=GUILD, name='VIce District'),
                  _target_id=GUILD, extra=None, before=before or {}, after=after or {},
                  created_at=WHEN, reason=None)
    values.update(kwargs)
    return NS(**values)


def api_entry(changes, *, identifier=1572718032730464406):
    """The same payload shape read from Discord, passed through its real library."""
    actor = user()
    guild = NS(id=GUILD, name='GTA VI Latino | VIce District', _state=None,
               get_member=lambda identifier: actor if identifier == ACTOR else None,
               get_channel=lambda identifier: None)
    return discord.AuditLogEntry(
        users={ACTOR: actor}, integrations={}, app_commands={}, automod_rules={}, webhooks={},
        guild=guild, data=dict(id=str(identifier), action_type=1, target_id=str(GUILD),
                               user_id=str(ACTOR), changes=changes))


def fields(embed):
    return {field.name: field.value for field in embed.fields}


def contents(embed):
    return json.dumps(embed.to_dict(), ensure_ascii=False)


class HumanReadableServerAuditTests(unittest.TestCase):
    def test_real_splash_hash_payload_is_transformed_and_still_describes_the_change(self):
        source = api_entry([dict(key='splash_hash', old_value=OLD_HASH, new_value=NEW_HASH)])
        self.assertIsInstance(source.before.splash, discord.Asset)
        self.assertIsInstance(source.after.splash, discord.Asset)
        result = format_audit_entry(source)
        self.assertEqual(result.description,
                         f'🖼️ <@{ACTOR}> cambió el fondo de invitación del servidor.')
        self.assertEqual(result.author.name, 'esschino')
        self.assertEqual(result.timestamp, source.created_at)
        self.assertEqual(fields(result)['IDs'],
                         f'Usuario: esschino (`{ACTOR}`)\n'
                         f'Servidor: GTA VI Latino \\| VIce District (`{GUILD}`)')
        self.assertNotIn('Actor', contents(result))
        self.assertNotIn('Afectado', contents(result))
        self.assertNotIn(OLD_HASH, contents(result))
        self.assertNotIn(NEW_HASH, contents(result))
        self.assertNotIn('Cambio', fields(result))  # The sentence already explains it.
        self.assertLess(len(result), 400)

    def test_real_added_banner_and_splash_payload_names_both_images(self):
        source = api_entry([
            dict(key='banner_hash', new_value='d6d13e237468d3c86258e9356ecfe49f'),
            dict(key='splash_hash', new_value='2352b7002eea5e49591f494c92bb876d'),
        ], identifier=1572713645840928869)
        result = format_audit_entry(source)
        self.assertEqual(result.description, f'<@{ACTOR}> actualizó la apariencia del servidor.')
        self.assertEqual(fields(result)['Cambio'],
                         'Banner del servidor: Imagen añadida\nFondo de invitación: Imagen añadida')
        self.assertNotIn('d6d13e237468d3c86258e9356ecfe49f', contents(result))
        self.assertNotIn('2352b7002eea5e49591f494c92bb876d', contents(result))

    def test_real_system_channel_payload_keeps_clickable_before_after_channels(self):
        source = api_entry([dict(key='system_channel_id', old_value='1572462547058032804',
                                 new_value='1572704521371652166')], identifier=1572704537846878409)
        result = format_audit_entry(source)
        self.assertIn('cambió el canal de notificaciones del servidor', result.description)
        self.assertEqual(fields(result)['Cambio'],
                         'Canal de notificaciones: <#1572462547058032804> → <#1572704521371652166>')

    def test_every_server_image_names_addition_replacement_and_removal_without_hashes(self):
        nouns = {'splash': 'el fondo de invitación del servidor', 'banner': 'el banner del servidor',
                 'icon': 'el icono del servidor',
                 'discovery_splash': 'la imagen de descubrimiento del servidor'}
        for key, noun in nouns.items():
            for old, new, verb in ((None, NEW_HASH, 'añadió'), (OLD_HASH, NEW_HASH, 'cambió'),
                                   (OLD_HASH, None, 'retiró')):
                with self.subTest(key=key, verb=verb):
                    result = format_audit_entry(entry({key: old}, {key: new}))
                    self.assertEqual(result.description, f'🖼️ <@{ACTOR}> {verb} {noun}.')
                    self.assertNotIn(OLD_HASH, contents(result))
                    self.assertNotIn(NEW_HASH, contents(result))

    def test_unchanged_asset_is_not_reported_as_a_replacement(self):
        source = api_entry([dict(key='banner_hash', old_value=OLD_HASH, new_value=OLD_HASH),
                            dict(key='name', old_value='Old', new_value='New')])
        result = format_audit_entry(source)
        self.assertIn('cambió el nombre del servidor', result.description)
        self.assertEqual(fields(result)['Cambio'], 'Nombre: Old → New')
        self.assertNotIn('banner', contents(result).lower())

    def test_long_values_are_compared_before_their_display_truncation(self):
        result = format_audit_entry(entry({'description': 'a' * 100 + 'before'},
                                         {'description': 'a' * 100 + 'after'}))
        self.assertIn('cambió la descripción del servidor', result.description)
        self.assertIn('Descripción: Actualizado', fields(result)['Cambio'])

    def test_name_description_and_boost_bar_are_plain_readable_changes(self):
        result = format_audit_entry(entry(
            {'name': 'Old', 'description': 'Antes', 'premium_progress_bar_enabled': False},
            {'name': 'VIce District', 'description': 'Ahora', 'premium_progress_bar_enabled': True}))
        change = fields(result)['Cambio']
        self.assertIn('Nombre: Old → VIce District', change)
        self.assertIn('Descripción: Antes → Ahora', change)
        self.assertIn('Barra de mejoras: No → Sí', change)
        self.assertNotIn('+', change)

    def test_unrecognized_setting_is_named_without_dumping_its_raw_values(self):
        result = format_audit_entry(entry(
            {'future_server_option': {'opaque': 'PRIVATE_BEFORE'}},
            {'future_server_option': {'opaque': 'PRIVATE_AFTER'}}))
        self.assertEqual(fields(result)['Cambio'], 'Future server option: Actualizado')
        self.assertNotIn('PRIVATE_', contents(result))
        self.assertIn('un ajuste del servidor', result.description)

    def test_sensitive_setting_names_and_values_are_never_rendered(self):
        result = format_audit_entry(entry(
            {'api_token': 'PRIVATE_BEFORE', 'name': 'Old'},
            {'api_token': 'PRIVATE_AFTER', 'name': 'New'}))
        self.assertEqual(fields(result)['Cambio'], 'Nombre: Old → New')
        self.assertNotIn('token', contents(result))
        self.assertNotIn('PRIVATE_', contents(result))

    def test_missing_details_and_missing_actor_are_not_invented(self):
        result = format_audit_entry(entry(user=None, user_id=None))
        self.assertEqual(result.description, 'Se actualizó el servidor.')
        self.assertEqual(fields(result)['Cambio'],
                         'Discord no detalló el ajuste modificado en este registro.')
        self.assertEqual(fields(result)['IDs'], f'Servidor: VIce District (`{GUILD}`)')
        self.assertIsNone(result.author.name)

    def test_ids_show_real_username_instead_of_server_display_name(self):
        actor = user()
        actor.display_name = 'El Fundador'
        result = format_audit_entry(entry(user=actor))
        self.assertEqual(fields(result)['IDs'],
                         f'Usuario: esschino (`{ACTOR}`)\nServidor: VIce District (`{GUILD}`)')
        self.assertNotIn('El Fundador', fields(result)['IDs'])

    def test_matching_actor_without_username_can_use_its_display_name(self):
        actor = user()
        actor.name, actor.display_name = '', 'El Fundador'
        result = format_audit_entry(entry(user=actor))
        self.assertIn(f'Usuario: El Fundador (`{ACTOR}`)', fields(result)['IDs'])

    def test_known_user_id_without_matching_user_name_remains_an_honest_id(self):
        for actor in (None, NS(name='Unverified user', display_name='Unverified display')):
            with self.subTest(actor=actor):
                result = format_audit_entry(entry(user=actor, user_id=ACTOR))
                self.assertEqual(fields(result)['IDs'],
                                 f'Usuario: `{ACTOR}`\nServidor: VIce District (`{GUILD}`)')
                self.assertNotIn('Unverified', fields(result)['IDs'])

    def test_matching_guild_supplies_name_when_target_is_unresolved(self):
        guild = NS(id=GUILD, name='GTA VI Latino | VIce District')
        for target in (None, discord.Object(id=GUILD)):
            with self.subTest(target=target):
                result = format_audit_entry(entry(target=target, guild=guild))
                self.assertEqual(fields(result)['IDs'],
                                 f'Usuario: esschino (`{ACTOR}`)\n'
                                 f'Servidor: GTA VI Latino \\| VIce District (`{GUILD}`)')

    def test_missing_target_id_can_use_the_audit_entry_guild_identity(self):
        result = format_audit_entry(entry(
            target=None, _target_id=None, guild=NS(id=GUILD, name='VIce District')))
        self.assertEqual(fields(result)['IDs'],
                         f'Usuario: esschino (`{ACTOR}`)\nServidor: VIce District (`{GUILD}`)')

    def test_unmatched_guild_or_unidentified_target_cannot_supply_server_name(self):
        for target in (None, discord.Object(id=GUILD), NS(name='Unidentified server')):
            with self.subTest(target=target):
                result = format_audit_entry(entry(
                    target=target, guild=NS(id=999999999999999999, name='Unrelated server')))
                self.assertEqual(fields(result)['IDs'],
                                 f'Usuario: esschino (`{ACTOR}`)\nServidor: `{GUILD}`')
                self.assertNotIn('Unrelated', fields(result)['IDs'])
                self.assertNotIn('Unidentified', fields(result)['IDs'])

    def test_absent_identities_are_not_invented(self):
        result = format_audit_entry(entry(user=None, user_id=None, target=None,
                                         _target_id=None, guild=None))
        self.assertNotIn('IDs', fields(result))
        self.assertIsNone(result.author.name)

    def test_long_names_are_bounded_without_truncating_either_id(self):
        actor = user()
        actor.name = 'a' * 300
        result = format_audit_entry(entry(user=actor, target=NS(id=GUILD, name='b' * 400)))
        value = fields(result)['IDs']
        self.assertEqual(value,
                         f'Usuario: {"a" * 79}… (`{ACTOR}`)\n'
                         f'Servidor: {"b" * 119}… (`{GUILD}`)')
        self.assertIn(f'`{ACTOR}`', value)
        self.assertIn(f'`{GUILD}`', value)
        self.assertLessEqual(len(value), 370)
        self.assertNotIn('+', value)

    def test_names_escape_markdown_and_mentions_without_changing_ids(self):
        actor = user()
        actor.name = 'user_*name*'
        result = format_audit_entry(entry(user=actor, target=NS(id=GUILD, name='**VICE** @everyone')))
        value = fields(result)['IDs']
        self.assertEqual(value,
                         f'Usuario: user\\_\\*name\\* (`{ACTOR}`)\n'
                         f'Servidor: \\*\\*VICE\\*\\* @\u200beveryone (`{GUILD}`)')
        self.assertNotIn('@everyone', value)

    def test_non_server_audit_descriptions_and_id_labels_are_unchanged(self):
        result = format_audit_entry(entry({'name': 'Old'}, {'name': 'New'},
                                         action=discord.AuditLogAction.channel_update))
        self.assertEqual(result.description, f'<@{ACTOR}> actualizó <#{GUILD}>.')
        self.assertEqual(fields(result)['IDs'], f'Actor `{ACTOR}` · Canal `{GUILD}`')
        self.assertEqual(fields(result)['Cambio'], 'Nombre: Old → New')


if __name__ == '__main__':
    unittest.main()
