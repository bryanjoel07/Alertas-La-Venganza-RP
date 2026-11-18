"""Compact audit cards keep useful evidence without configuration dumps."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace as NS
import unittest

import discord

from vice_audit_format import (
    ACTION_NAMES, AMBER, GREEN, RED, compact_stored_embed, format_audit_entry,
)

WHEN = datetime(2026, 11, 18, 13, 20, tzinfo=timezone.utc)
ACTOR, TARGET, CHANNEL = 111111111111111111, 222222222222222222, 333333333333333333


def user(identifier=ACTOR, name='EssChino'):
    return NS(id=identifier, name=name, display_name=name,
              display_avatar=NS(url=f'https://cdn.discordapp.com/avatars/{identifier}/test.png'))


def entry(action=discord.AuditLogAction.channel_update, **kwargs):
    values = dict(id=1572462544302383164, action=action, user=user(), user_id=ACTOR,
                  target=NS(id=TARGET, name='general'), _target_id=TARGET, extra=None,
                  before={}, after={}, created_at=WHEN, reason=None)
    values.update(kwargs)
    return NS(**values)


def contents(embed):
    return json.dumps(embed.to_dict(), ensure_ascii=False)


def field(embed, name):
    return next(f.value for f in embed.fields if f.name == name)


def legacy(title, **kwargs):
    result = discord.Embed(title=title, description=kwargs.get('description'), color=AMBER, timestamp=WHEN)
    result.set_author(name='EssChino', icon_url=f'https://cdn.discordapp.com/avatars/{ACTOR}/test.png')
    result.set_footer(text='VIce District • Histórico de auditoría • 18/11/2026 09:20:00 AST • ref:0123456789abcdef01234')
    for name, value in kwargs.get('fields', {}).items():
        result.add_field(name=name, value=value, inline=False)
    return result


class AuditFormatTests(unittest.TestCase):
    def test_all_known_actions_are_compact_and_time_is_original(self):
        for action in discord.AuditLogAction:
            with self.subTest(action=action.name):
                self.assertIn(action.value, ACTION_NAMES)
                embed = format_audit_entry(entry(action))
                self.assertIsNone(embed.title)
                self.assertLessEqual(len(embed), 650)
                self.assertLessEqual(len(embed.fields), 3)
                self.assertEqual(embed.timestamp, WHEN)
                self.assertEqual(embed.footer.text, 'VIce District • 18/11 09:20 AST')

    def test_create_delete_update_color(self):
        for action, color in ((discord.AuditLogAction.role_create, GREEN),
                              (discord.AuditLogAction.channel_delete, RED),
                              (discord.AuditLogAction.channel_update, AMBER)):
            self.assertEqual(format_audit_entry(entry(action)).color.value, color)

    def test_actor_mention_avatar_changed_name_and_reason_are_not_repeated(self):
        result = format_audit_entry(entry(before={'name': 'general'}, after={'name': 'charla'},
                                         reason='Ordenar el corillo'), historical=True)
        self.assertEqual(result.description, f'<@{ACTOR}> actualizó <#{TARGET}>.')
        self.assertEqual(result.author.name, 'EssChino')
        self.assertIn(f'/{ACTOR}/', result.author.icon_url)
        self.assertEqual(field(result, 'Cambio'), 'Nombre: general → charla')
        self.assertEqual(field(result, 'Razón'), 'Ordenar el corillo')
        self.assertEqual(field(result, 'IDs').count(str(ACTOR)), 1)
        self.assertEqual(field(result, 'IDs').count(str(TARGET)), 1)
        self.assertNotIn('Histórico', result.footer.text)

    def test_permission_overwrite_shows_only_changes_and_three_states(self):
        old = dict(allow=discord.Permissions(view_channel=True, send_messages=True),
                   deny=discord.Permissions(embed_links=True))
        new = dict(allow=discord.Permissions(view_channel=True),
                   deny=discord.Permissions(send_messages=True))
        result = format_audit_entry(entry(discord.AuditLogAction.overwrite_update,
            before=old, after=new, extra=NS(id=CHANNEL, name='Miembro', type=discord.Role)))
        change = field(result, 'Cambio')
        self.assertIn('❌ Enviar mensajes', change)
        self.assertIn('↩️ Insertar enlaces', change)
        self.assertNotIn('Ver canal', change)
        self.assertNotIn(str(old['allow'].value), change)
        self.assertNotIn('Antes', change)
        self.assertNotIn('Después', change)
        self.assertIn(f'<@&{CHANNEL}>', result.description)

    def test_permission_limit_is_five_plus_remainder_and_no_raw_masks(self):
        result = format_audit_entry(entry(discord.AuditLogAction.role_update,
            before={'permissions': discord.Permissions.none()},
            after={'permissions': discord.Permissions.all()}))
        change = field(result, 'Cambio')
        self.assertEqual(change.count('✅'), 5)
        self.assertRegex(change, r'\+\d+ más')
        self.assertNotIn(str(discord.Permissions.all().value), change)
        self.assertLess(len(result), 650)

    def test_overwrite_create_and_delete_map_to_allow_deny_inherit(self):
        created = format_audit_entry(entry(discord.AuditLogAction.overwrite_create,
            after={'allow': discord.Permissions(view_channel=True),
                   'deny': discord.Permissions(send_messages=True)}))
        self.assertIn('✅ Ver canal', field(created, 'Cambio'))
        self.assertIn('❌ Enviar mensajes', field(created, 'Cambio'))
        deleted = format_audit_entry(entry(discord.AuditLogAction.overwrite_delete,
            before={'allow': discord.Permissions(view_channel=True)}))
        self.assertIn('↩️ Ver canal', field(deleted, 'Cambio'))

    def test_create_and_delete_do_not_dump_entire_object_configuration(self):
        for action in (discord.AuditLogAction.channel_create, discord.AuditLogAction.channel_delete):
            result = format_audit_entry(entry(action, after={'topic': 'FULL_CONFIG_SHOULD_NOT_APPEAR',
                'permissions': discord.Permissions.all(), 'nsfw': False, 'overwrites': ['many rows']}))
            self.assertNotIn('FULL_CONFIG_SHOULD_NOT_APPEAR', contents(result))
            self.assertFalse(any(f.name == 'Cambio' for f in result.fields))

    def test_voice_move_disconnect_never_name_a_specific_subject(self):
        for action in (discord.AuditLogAction.member_move, discord.AuditLogAction.member_disconnect):
            result = format_audit_entry(entry(action, target=user(TARGET, 'Not a proven subject'),
                extra=NS(count=3, channel=NS(id=CHANNEL, name='Soporte'))))
            self.assertNotIn(str(TARGET), contents(result))
            self.assertNotIn('Not a proven subject', contents(result))
            self.assertIn('3 miembros', result.description)
            self.assertNotIn('Alcance', contents(result))
            self.assertLess(len(result), 500)

    def test_roles_are_added_removed_mentions_and_no_full_membership_snapshot(self):
        result = format_audit_entry(entry(discord.AuditLogAction.member_role_update,
            target=user(TARGET), before={'roles': [NS(id=444444444444444444)]},
            after={'roles': [NS(id=555555555555555555)]}))
        self.assertEqual(field(result, 'Cambio'), '+ <@&555555555555555555> · − <@&444444444444444444>')
        self.assertNotIn('Antes', contents(result))

    def test_private_departure_reason_is_omitted_instead_of_an_explanation_field(self):
        for action in (discord.AuditLogAction.kick, discord.AuditLogAction.ban):
            result = format_audit_entry(entry(action, target=user(TARGET), reason='PRIVATE_CAUSE',
                before={'reason': 'PRIVATE_CAUSE'}, after={'nested': {'reason': 'PRIVATE_CAUSE'}}))
            self.assertNotIn('PRIVATE_CAUSE', contents(result))
            self.assertFalse(any(f.name in ('Razón', 'Motivo') for f in result.fields))
            self.assertIn(f'/{TARGET}/', result.thumbnail.url)

    def test_reason_only_when_nonempty_and_maximum_160(self):
        for reason in (None, '', '   '):
            self.assertFalse(any(f.name == 'Razón' for f in format_audit_entry(entry(reason=reason)).fields))
        result = format_audit_entry(entry(reason='x' * 3000))
        self.assertEqual(len(field(result, 'Razón')), 160)

    def test_sanitizes_secrets_user_text_and_disallows_external_avatar(self):
        actor = user(name='@everyone **ADMIN**')
        actor.display_avatar.url = 'https://example.com/tracker'
        token = 'A' * 24 + '.' + 'B' * 6 + '.' + 'C' * 30
        webhook = 'https://discord.com/api/webhooks/123/WEBHOOK_SECRET'
        result = format_audit_entry(entry(user=actor,
            reason=webhook + ' token=abcdef ' + token,
            before={'content': 'PRIVATE_MESSAGE', 'token': 'TOKEN_VALUE'},
            after={'name': '@here **name**'}))
        raw = contents(result)
        for secret in ('WEBHOOK_SECRET', 'abcdef', token, 'PRIVATE_MESSAGE', 'TOKEN_VALUE'):
            self.assertNotIn(secret, raw)
        self.assertIsNone(result.author.icon_url)
        self.assertNotIn('@everyone', result.author.name)
        self.assertIn(f'<@{ACTOR}>', result.description)

    def test_hard_bound_for_long_names_reasons_and_changes(self):
        result = format_audit_entry(entry(user=user(name='n' * 1000), reason='r' * 2000,
            before={'name': 'a' * 1000, 'topic': 'b' * 1000}, after={'name': 'c' * 1000, 'topic': 'd' * 1000}))
        self.assertLessEqual(len(result), 1050)
        self.assertLessEqual(len(result.fields), 3)
        self.assertLessEqual(len(field(result, 'Cambio')), 180)
        self.assertLessEqual(len(result.author.name), 80)

    def test_missing_actor_not_falsely_attributed_to_discord(self):
        result = format_audit_entry(entry(user=None, user_id=None))
        self.assertIsNone(result.author.name)
        self.assertNotIn('Discord actualizó', result.description)
        self.assertNotIn('no disponible', contents(result))

    def test_message_delete_identifies_author_count_and_channel_without_content(self):
        result = format_audit_entry(entry(discord.AuditLogAction.message_delete,
            target=user(TARGET), extra=NS(count=4, channel=NS(id=CHANNEL, name='chat'))))
        self.assertIn('4 mensajes', result.description)
        self.assertIn(f'de <@{TARGET}>', result.description)
        self.assertIn(f'en <#{CHANNEL}>', result.description)
        self.assertLess(len(result), 650)

    def test_stored_voice_move_compacts_avatar_time_channels_and_deduplicates_ids(self):
        source = legacy('🔀 Cambio de canal de voz', description=f'<@{TARGET}> cambió de canal de voz.',
            fields={'Usuario': f'<@{TARGET}> · username',
                    'Canal': f'<#{ACTOR}> · Origen\n➡️ <#{CHANNEL}> · Destino',
                    'Autoría': 'Este evento no identifica responsable.',
                    'IDs': f'Usuario: {chr(96)}{TARGET}{chr(96)}\nOrigen: {chr(96)}{ACTOR}{chr(96)}\nDestino: {chr(96)}{CHANNEL}{chr(96)}'})
        result = compact_stored_embed(source, event_type='voice_move')
        self.assertEqual(result.description, f'<@{TARGET}> cambió de <#{ACTOR}> a <#{CHANNEL}>.')
        self.assertEqual(result.timestamp, WHEN)
        self.assertEqual(result.author.icon_url, source.author.icon_url)
        self.assertNotIn('ref:', contents(result))
        self.assertFalse(any(f.name == 'Autoría' for f in result.fields))
        self.assertEqual(field(result, 'IDs').count(str(TARGET)), 1)
        self.assertLess(len(result), 500)

    def test_stored_member_leave_preserves_action_but_not_private_reason(self):
        source = legacy('📤 Salió del servidor', description=f'<@{TARGET}> salió del servidor.',
            fields={'Usuario': f'<@{TARGET}>', 'Motivo': 'PRIVATE_DEPARTURE',
                    'Información de salida': 'Mucho texto de explicación',
                    'IDs': f'Usuario: {chr(96)}{TARGET}{chr(96)}'})
        result = compact_stored_embed(source.to_dict(), event_type='member_leave')
        self.assertEqual(result.description, f'<@{TARGET}> salió del servidor.')
        self.assertNotIn('PRIVATE_DEPARTURE', contents(result))
        self.assertLess(len(result), 350)

    def test_stored_full_permission_masks_become_only_changed_permissions(self):
        old = discord.Permissions(view_channel=True, send_messages=True).value
        new = discord.Permissions(view_channel=True).value
        source = legacy('🟠 Permiso de canal actualizado', fields={
            'Responsable': f'<@{ACTOR}> · EssChino ({ACTOR})',
            'Objeto afectado': f'<#{CHANNEL}> · chat',
            'Permiso aplicado a': '<@&444444444444444444>',
            'Permitir': f'**Antes:** Ver canal, Enviar mensajes · {chr(96)}{old}{chr(96)}\n**Después:** Ver canal · {chr(96)}{new}{chr(96)}',
            'Denegar': '**Antes:** Ninguno · ' + chr(96) + '0' + chr(96) + '\n**Después:** Ninguno · ' + chr(96) + '0' + chr(96),
            'Motivo': 'No indicado en la auditoría de Discord.',
            'IDs': f'Responsable: {chr(96)}{ACTOR}{chr(96)}\nCanal: {chr(96)}{CHANNEL}{chr(96)}'})
        result = compact_stored_embed(source)
        self.assertEqual(field(result, 'Cambio'), '↩️ Enviar mensajes')
        self.assertNotIn(str(old), field(result, 'Cambio'))
        self.assertNotIn('No indicado', contents(result))
        self.assertLess(len(result), 650)

    def test_stored_group_actions_do_not_reintroduce_unproven_subject(self):
        source = legacy('🟠 Miembros movidos en voz', fields={
            'Responsable': f'<@{ACTOR}>', 'Objeto afectado': f'<@{TARGET}>',
            'Canal de destino': f'<#{CHANNEL}>', 'Cantidad acumulada': '2',
            'IDs': f'Responsable: {chr(96)}{ACTOR}{chr(96)}\nAfectado: {chr(96)}{TARGET}{chr(96)}'})
        result = compact_stored_embed(source)
        self.assertNotIn(str(TARGET), contents(result))
        self.assertIn('2 miembros', result.description)

    def test_stored_large_unknown_cards_are_safe_bounded_and_have_no_legacy_footer(self):
        source = legacy('Actividad de prueba', description='x' * 9000,
            fields={'Cambio': 'y' * 9000, 'Motivo': 'z' * 9000,
                    'IDs': '\n'.join(f'Usuario: {chr(96)}{100000000000000000+i}{chr(96)}' for i in range(50))})
        result = compact_stored_embed(source)
        self.assertLessEqual(len(result), 1050)
        self.assertLessEqual(len(result.fields), 3)
        self.assertNotIn('ref:', contents(result))
        self.assertNotIn('Histórico', result.footer.text)


if __name__ == '__main__':
    unittest.main()
