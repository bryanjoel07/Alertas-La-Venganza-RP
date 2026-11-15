# Discord administration constraints

The owner explicitly forbids modifying these roles, including permissions, channel overwrites, names, colors, position, and member assignments:
- Owner: 1245008186440683530
- Programador: 1300627506801541230
- Admin: 1300619682486947931
- Súper Admin: 1245010156576833536

Read-only inspection is allowed. Do not remove existing staff access as part of organizing channels or roles. Naming command channels does not authorize restricting staff permissions. Preserve Citizen writing permissions. Never delete channels or their history when organizing navigation.

Targeted later authorization (2026-11-10): the owner explicitly requests removing all role memberships from his two accounts with exact usernames `esschino__` and `esschino_`, keeping only Ciudadanos (1245009164070158409). For this one request only, protected staff role memberships may also be removed from these two verified account IDs. Persist their exact IDs and original memberships before acting. This does not authorize editing role definitions, permissions, positions, other members, or repeating a completed cleanup. Discord's implicit @everyone remains.

Verified account IDs: `esschino__` is 1146879020911300628 and `esschino_` is 1509288420852109383. The owner explicitly renewed removal of their remaining staff memberships after the first partial result. A second one-shot request may retry only the original saved role list on those accounts; record Discord's actual response and preserve both before-states. This does not grant authority to change role definitions or hierarchy.

For every future bot deployment, update `RELEASE`, `SUMMARY`, and `RESTORE` in `change_log.py` to describe the actual change and a correct previous commit/restoration procedure. Route new administrative Discord mutations through `ChangeLog.tracked` so the before-state is durable before mutation. Read REGISTRO_CAMBIOS.md for restoration limits. Do not claim to log manual Discord edits automatically.

Later explicit authorization: replace the old official bug-report template shown by the owner (starter message and information post 1564719087798460466 in forum 1556488595131466000) with a new, organized bot-owned message and its buttons, and delete that old template. Forum starter removal can remove its information post. This exception applies only to that exact old information post, after a verified durable copy and a verified new bot-owned replacement. Delete it only if its remaining messages are this bot's entry buttons and it has no files, third-party replies or linked real report. Preserve/archive it instead if those checks fail. No other report, channel, permission or role is authorized for deletion or alteration by this exception.

The owner explicitly authorizes a staff-only deletion button for closed tickets managed by this bot, after confirmation and a verified transcript/evidence backup. This exception does not authorize deleting other channels, open tickets, legacy tickets, or protected roles. Preserve archived ticket records and proof blobs after deleting the Discord channel.

The owner now explicitly authorizes adding view_channel and read_message_history on the Tickets Cerrados category and normal closed ticket channels for Owner, Programador, Jefe de Admin/Staff, Súper Admin, Admin, Moderador and Soporte. This targeted exception does not authorize changing their guild permission bits, positions, membership or unrelated overwrites. Reserved staff reports retain their restricted access. The owner also explicitly requests clearing all messages in Registro Exclusive (1569084826324046028) and stopping bot-change announcements there; keep a verified private backup before the one-shot purge.

Later explicit authorization: add an administrator-only, confirmed deletion action for ideas managed by this bot in Sugerencias (1539013973947588759). It may delete the verified bot-owned idea message (or its own dedicated forum post if used there) and hard-delete that idea, its votes and decision rows from the suggestion tables. Save a durable private before-state first and verify Discord removal before purging the active records. This grants no permission to delete other messages, channels, legacy bot posts, tickets or roles; preserve protected role definitions, memberships and overwrites.
