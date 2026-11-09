# Discord administration constraints

The owner explicitly forbids modifying these roles, including permissions, channel overwrites, names, colors, position, and member assignments:
- Owner: 1245008186440683530
- Programador: 1300627506801541230
- Admin: 1300619682486947931
- Súper Admin: 1245010156576833536

Read-only inspection is allowed. Do not remove existing staff access as part of organizing channels or roles. Naming command channels does not authorize restricting staff permissions. Preserve Citizen writing permissions. Never delete channels or their history when organizing navigation.

For every future bot deployment, update `RELEASE`, `SUMMARY`, and `RESTORE` in `change_log.py` to describe the actual change and a correct previous commit/restoration procedure. Route new administrative Discord mutations through `ChangeLog.tracked` so the before-state is durable before mutation. Read REGISTRO_CAMBIOS.md for restoration limits. Do not claim to log manual Discord edits automatically.

The owner explicitly authorizes a staff-only deletion button for closed tickets managed by this bot, after confirmation and a verified transcript/evidence backup. This exception does not authorize deleting other channels, open tickets, legacy tickets, or protected roles. Preserve archived ticket records and proof blobs after deleting the Discord channel.
