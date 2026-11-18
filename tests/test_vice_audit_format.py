"""Audit cards preserve evidence, secrets and Discord message limits."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace as NS
import unittest

import discord

from vice_audit_format import ACTION_NAMES, AMBER, GREEN, RED, format_audit_entry


WHEN = datetime(2026, 11, 18, 13, 20, tzinfo=timezone.utc)


def user(identifier=77, name='EssChino'):
    return NS(id=identifier, name=name, display_name=name,
              display_avatar=NS(url=f'https://cdn.discordapp.com/avatars/{identifier}/test.png'))


def entry(action=discord.AuditLogAction.channel_update, **kwargs):
    values = dict(id=1572462544302383164, action=action, user=user(), user_id=77,
                  target=NS(id=88, name='general'), _target_id=88, extra=None,
                  before={}, after={}, created_at=WHEN, reason=None)
    values.update(kwargs)
    return NS(**values)


def contents(embed):
    return json.dumps(embed.to_dict(), ensure_ascii=False)


def field(embed, name):
    return next(f.value for f in embed.fields if f.name == name)


class AuditFormatTests(unittest.TestCase):
    def test_all_installed_actions_have_spanish_title_and_safe_payload(self):
        for action in discord.AuditLogAction:
            with self.subTest(action=action.name):
                self.assertIn(action.value, ACTION_NAMES)
                embed = format_audit_entry(entry(action))
                self.assertIn(ACTION_NAMES[action.value], embed.title)
                self.assertLessEqual(len(embed), 5500)
                self.assertEqual(embed.timestamp, WHEN)

    def test_create_delete_and_update_use_distinct_colors(self):
        for action, color in ((discord.AuditLogAction.role_create, GREEN),
                              (discord.AuditLogAction.channel_delete, RED),
                              (discord.AuditLogAction.channel_update, AMBER)):
            with self.subTest(action=action):
                self.assertEqual(format_audit_entry(entry(action)).color.value, color)

    def test_actor_original_time_avatar_ids_and_before_after_are_evidenced(self):
        obj = entry(before=NS(name='general', slowmode_delay=0),
                    after=NS(name='charla', slowmode_delay=30), reason='Ordenar el corillo')
        embed = format_audit_entry(obj, historical=True)
        self.assertEqual(embed.author.name, 'EssChino')
        self.assertIn('/77/test.png', embed.author.icon_url)
        self.assertIn('<@77>', field(embed, 'Responsable'))
        self.assertIn('general', field(embed, 'Nombre'))
        self.assertIn('charla', field(embed, 'Nombre'))
        self.assertIn('Antes', field(embed, 'Modo lento (segundos)'))
        self.assertIn('30', field(embed, 'Modo lento (segundos)'))
        self.assertIn('`88`', field(embed, 'IDs'))
        self.assertIn(str(obj.id), field(embed, 'IDs'))
        self.assertEqual(field(embed, 'Motivo'), 'Ordenar el corillo')
        self.assertIn('09:20:00 AST', embed.footer.text)
        self.assertIn('Histórico', embed.footer.text)
        self.assertEqual(embed.timestamp, WHEN)

    def test_group_voice_move_never_claims_affected_member_or_source(self):
        obj = entry(discord.AuditLogAction.member_move, target=user(999, 'SHOULD NOT APPEAR'),
                    _target_id=999, extra=NS(count=3, channel=NS(id=66, name='Soporte')))
        embed = format_audit_entry(obj)
        body = contents(embed)
        self.assertNotIn('999', body)
        self.assertNotIn('SHOULD NOT APPEAR', body)
        self.assertEqual(field(embed, 'Cantidad acumulada'), '3')
        self.assertIn('<#66>', field(embed, 'Canal de destino'))
        self.assertIn('no identifica', field(embed, 'Alcance del registro'))
        self.assertIn('canal de origen', field(embed, 'Alcance del registro'))
        self.assertIn('`77`', field(embed, 'IDs'))

    def test_group_disconnect_does_not_invent_channel_or_subject(self):
        embed = format_audit_entry(entry(discord.AuditLogAction.member_disconnect,
                                  target=user(999), _target_id=999, extra=NS(count=2)))
        self.assertNotIn('999', contents(embed))
        self.assertEqual(field(embed, 'Cantidad acumulada'), '2')
        self.assertFalse(any(f.name == 'Canal de destino' for f in embed.fields))

    def test_kick_and_ban_reason_cannot_leak_through_entry_or_nested_diff(self):
        for action in (discord.AuditLogAction.kick, discord.AuditLogAction.ban):
            with self.subTest(action=action):
                embed = format_audit_entry(entry(action, target=user(99), reason='CONFIDENTIAL_OUTCOME',
                    before={'reason': 'CONFIDENTIAL_OUTCOME', 'nested': {'audit_reason': 'CONFIDENTIAL_OUTCOME'}},
                    after={'reason': 'CONFIDENTIAL_OUTCOME'}))
                self.assertNotIn('CONFIDENTIAL_OUTCOME', contents(embed))
                self.assertIn('exclusivo de Administración', field(embed, 'Motivo'))
                self.assertIn('/99/test.png', embed.thumbnail.url)

    def test_secrets_message_content_and_webhook_urls_are_not_serialized(self):
        token = 'A' * 24 + '.' + 'B' * 6 + '.' + 'C' * 30
        webhook = 'https://discord.com/api/v10/webhooks/123456789/VERY_SECRET_TOKEN'
        embed = format_audit_entry(entry(discord.AuditLogAction.webhook_update,
            target=NS(id=333, name='Webhook'),
            before={'token': 'NEVER_TOKEN', 'content': 'PRIVATE_MESSAGE', 'url': webhook,
                    'description': webhook + ' token=abc123 ' + token},
            after={'nested': {'password': 'NEVER_PASSWORD', 'name': 'Visible'}},
            reason='Comprobar ' + webhook + ' secret=xyz123'))
        body = contents(embed)
        for value in ('NEVER_TOKEN', 'PRIVATE_MESSAGE', 'NEVER_PASSWORD', 'VERY_SECRET_TOKEN',
                      token, 'abc123', 'xyz123', webhook):
            self.assertNotIn(value, body)
        self.assertIn('Visible', body)
        self.assertIn('webhook oculto', body)

    def test_pathological_diff_remains_bounded_with_core_evidence_retained(self):
        changes = {f'field_{i}': 'z' * 5000 for i in range(60)}
        embed = format_audit_entry(entry(before=changes, after=changes,
                                  user=user(77, 'long' * 200), reason='reason' * 1000))
        self.assertLessEqual(len(embed), 5400)
        self.assertLessEqual(len(embed.fields), 24)
        self.assertLessEqual(len(embed.author.name), 150)
        self.assertTrue(all(len(f.value) <= 1024 and len(f.name) <= 128 for f in embed.fields))
        self.assertIn('`77`', field(embed, 'IDs'))
        self.assertIn('Motivo', [f.name for f in embed.fields])

    def test_missing_actor_preserves_id_without_assigning_blame(self):
        embed = format_audit_entry(entry(user=None, user_id=123, target=None, _target_id=456))
        self.assertIn('<@123>', field(embed, 'Responsable'))
        self.assertEqual(embed.author.name, 'Responsable no disponible')
        self.assertIn('`456`', field(embed, 'IDs'))
        unknown = format_audit_entry(entry(user=None, user_id=None))
        self.assertEqual(field(unknown, 'Responsable'), 'Discord no identifica al responsable.')

    def test_roles_are_added_and_removed_sets_not_full_before_after_membership(self):
        embed = format_audit_entry(entry(discord.AuditLogAction.member_role_update,
            before={'roles': [NS(id=1, name='Miembro')]},
            after={'roles': [NS(id=2, name='Ciudadano')]}))
        self.assertIn('<@&1>', field(embed, 'Roles retirados'))
        self.assertIn('<@&2>', field(embed, 'Roles añadidos'))
        self.assertFalse(any(f.name == 'Roles' for f in embed.fields))

    def test_permissions_are_readable_and_keep_exact_bitfield(self):
        before = discord.Permissions(view_channel=True)
        after = discord.Permissions(view_channel=True, manage_messages=True, moderate_members=True)
        embed = format_audit_entry(entry(discord.AuditLogAction.role_update,
                                  before={'permissions': before}, after={'permissions': after}))
        permissions = field(embed, 'Permisos')
        self.assertIn('Gestionar mensajes', permissions)
        self.assertIn('Tiempo de espera', permissions)
        self.assertIn(str(after.value), permissions)

    def test_message_delete_target_is_author_and_never_claims_message_content(self):
        embed = format_audit_entry(entry(discord.AuditLogAction.message_delete,
            target=user(99, 'Autor'), _target_id=99, extra=NS(count=4, channel=NS(id=66, name='chat'))))
        self.assertIn('<@99>', field(embed, 'Autor de los mensajes'))
        self.assertIn('<#66>', field(embed, 'Canal'))
        self.assertEqual(field(embed, 'Cantidad acumulada'), '4')

    def test_markdown_mentions_and_external_avatar_are_not_trusted(self):
        actor = user(name='@everyone **ADMIN**')
        actor.display_avatar.url = 'https://example.com/track-user'
        embed = format_audit_entry(entry(user=actor, reason='@here **hello**'))
        self.assertNotIn('@everyone', embed.author.name)
        self.assertNotIn('@here', field(embed, 'Motivo'))
        self.assertIn('\\*', embed.author.name)
        self.assertIsNone(embed.author.icon_url)

    def test_new_unknown_enum_value_still_gets_documented_action_name(self):
        for code in (16, 33, 192, 193):
            embed = format_audit_entry(entry(NS(value=code)))
            self.assertIn(ACTION_NAMES[code], embed.title)
        fallback = format_audit_entry(entry(NS(value=999)))
        self.assertIn('999', fallback.title)

    def test_unserializable_object_does_not_dump_private_attributes_or_repr(self):
        class SecretObject:
            token = 'SECRET_OBJECT_TOKEN'
            def __str__(self):
                return self.token
            def __repr__(self):
                return self.token
        embed = format_audit_entry(entry(after={'unexpected': SecretObject()}))
        self.assertNotIn('SECRET_OBJECT_TOKEN', contents(embed))
        self.assertIn('Valor registrado por Discord', field(embed, 'Unexpected'))


if __name__ == '__main__':
    unittest.main()
