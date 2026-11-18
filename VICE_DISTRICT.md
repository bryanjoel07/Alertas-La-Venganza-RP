# GTA VI Latino | VIce District

Owner-authorized community release: `vice-district-community-v4-pr`, 2026-11-17.
Visual naming migration: `vice-decorated-channels-v1`, 2026-11-18. Category
headers use heavy line separators and channels use matching first/middle/last
branches with emoji labels. This tracked migration edits names only, using saved
IDs; it never changes parent categories, ordering, permission overwrites or
message history. Existing and future tickets share the same visual style.
The private departures channel retains its explicit admin-only permissions.
Additive staff migration: `vice-staff-departures-v2-admin-only`, 2026-11-18.
Adds a private departures channel and the Administrator role without rebuilding
the community layout or reposting the welcome sample. Administrator has full
Discord Administrator permission and remains unassigned until the owner chooses
trusted people. Moderation can handle messages, pins, threads, nicknames, timeouts,
kicks, bans, voice moderation and audit logs, but cannot manage server settings,
roles, channels or webhooks. Support has ordinary communication permissions,
private staff/ticket access and message moderation only inside open tickets.
Departures are visible only to Founder and Administrator, with explicit channel
denials for Moderation and Support. Each record has an individualized farewell
banner, avatar, identity, departure time and known joining time. The bot looks for
matching recent kick/ban audit events (with brief retries for audit propagation)
and displays their recorded reason and actor. Without matching evidence it makes
no claim about the member's personal motive; unavailable audit data is disclosed.
The raw member remove event covers members absent from Discord's cache. A private
admin-only channel is required before posting. Membership receipts prevent duplicate
cached events. The initial private panel includes a clearly labeled banner sample
using the owner's profile; it is not a real departure. Assets and prompt are in
assets/vice-district/goodbye-template.jpg and goodbye-prompt.txt (built-in imagegen).
All these changes use the separate district journal and database.
Puerto Rico is the community's primary identity, welcoming all of Latin America.
The banner, description and welcome reflect this; Puerto Rico is the first optional
region and the reference timezone for future event announcements.
The welcome panel has no role menu or role-menu button, as explicitly requested.
Role selections live only in their dedicated channel (and the optional /vice roles command).
Guild: `1572462544302383164`. Bot: `1571639486591402174` (EssChino Studio Bot).

The existing Studio guild retains its handlers, store layout and `/data/esschino.sqlite3`.
VIce District uses a separate `/data/vice-district.sqlite3`, exact guild and owner checks,
its own command group `/vice`, persistent component IDs prefixed `vice:v1:` and welcome receipts.

The layout contains seven main categories and 23 permanent channels: arrival, community,
GTA discussion, voice, temporary rooms, support and private staff, plus the private ticket archive. There are 22 human roles (including
the existing Founder), four visual separator roles, plus the bot's managed role. The
lowest role, Miembro, is assigned automatically on joining. Accepting the rules through
the welcome button promotes Miembro to Ciudadano. Veterano and Leyenda de Vice are
manual recognition ranks; no automatic XP or activity-based promotions are claimed.
Optional platform, region and
notification roles have zero administrative permissions; staff roles are never offered
by the role menus. Moderation has message, timeout and voice tools without Administrator.

Welcome cards use the owner's supplied GTA artwork, edited with the built-in image
generation tool, then compose each member's real current avatar, display name and handle
with Pillow. Names are sanitized and fitted to the banner. The image is attached to
Discord, and does not depend on expiring external image URLs. `Mi bienvenida` is private.
The public owner example is explicitly labeled as a sample. Automatic join delivery
uses a durable receipt, retry recovery and attachment-based duplicate reconciliation.

Support creates one private active ticket per person. Owner, Moderation, Soporte and
the bot can access it. Closing moves the same channel into a private archive and
preserves its history and the requester's read access; no ticket deletion is implemented.

Initial provisioning runs once per release and reuses the existing roles/channels.
It never deletes roles, permanent channels or messages. Only registered empty temporary voice rooms
are cleaned up under the explicitly requested lifecycle below. Every configuration operation, role change,
ticket operation and automatic welcome goes through ChangeLog.tracked with durable
before/after state. Informational panels are pinned and recovered by their bot-authored
footer markers if a deployment is interrupted.

## Corillo tools — 2026-11-18

`vice_voice.py` adds a decorated category and persistent Crear mi sala / Administrar mi sala
panel. Each person can own one temporary voice room, with 6 seats by default and a 1–20
range. Controls for access, invitations, rename and capacity are private to the creator;
they do not grant server permissions. Founder, Administrator, Moderation and the bot
retain access. No automatic voice move is performed. Text chat is disabled in temporary
rooms to avoid deleting conversation history. Empty unused rooms expire after 120 seconds;
previously occupied rooms after 30 seconds. Cleanup checks live voice_states and only
deletes the exact registered VoiceChannel in the dedicated guild/category. The database
stores a nonce before creation; interrupted creation is recovered only from the exact
bot-authored audit entry, never from a channel name. All changes are journaled.

`vice_community.py` installs six original transparent emojis (VI, Puerto Rico, palm, fire,
heart, GG) and three stickers (¡WEPA!, ¡DURO!, PA’L CORILLO). The manifests under
assets/vice-district/emojis and stickers preserve final prompts and built-in imagegen
provenance. Existing unrelated expressions are preserved; capacity is checked first.

The opening calendar contains native Discord voice events in the public Lobby, with
Me interesa registration: GTA night on November 20, clip contest on November 27, and
GTA trivia on December 4, 2026, all at 20:00 Puerto Rico (AST, UTC−4). Each description
states rules, meeting place and the reference timezone. Staff hosts and starts each event.
The public agenda has a persistent button for upcoming events. `/vice evento` opens a
date/duration/description form for Founder, Administrator or Moderation; Support cannot
publish events. Dates are parsed as Puerto Rico time, with future/date-range validation.
Guild-scoped command synchronization, event creation and public panels are journaled.
Markers and exact creator/name/start recovery prevent duplicate opening events on restart.

## Validation

### Private audit history and live activity

`vice_audit.py` imports all audit entries Discord still makes available (up to its
45-day retention) into the existing private registro-staff channel, preserving original
timestamps and showing Puerto Rico AST in each footer. Initial historical records are
published chronologically in bounded batches of up to five embeds. The pinned staff
panel provides a short color legend and Puerto Rico time reference. No roles or access permissions are changed.

`vice_activity.py` records member arrivals/departures and observed voice connections,
disconnections, channel transitions, mute/deaf, camera and streaming changes from
activation onward. Gateway voice changes do not identify an administrative actor;
separate evidenced audit entries supply the actor and grouped count when Discord does.
The formatter includes avatars, names, IDs, relevant channels and before/after values,
with explicit unavailable values instead of guesses. Kick/ban reasons remain reserved
to admin-only departures. Message bodies and webhook/token credentials are not copied.

`vice_audit_store.py` keeps a durable SQLite outbox, payload fingerprints, message IDs,
send reservations and a transactionally advanced scan cursor. Gateway delivery and
polling share audit-entry keys. A one-hour overlapping scan every minute refreshes
merged entries whose counts change without a Gateway notification; a daily full scan
reconciles retained history. A single publisher edits existing merged records rather
than posting duplicates. Stable versioned nonces and exact embed URL-marker recovery cover
send-before-ack interruptions. Each Discord write uses a small durable ChangeLog snapshot.
Publication fails closed if registro-staff loses its private staff-only overwrite scope.

`vice-audit-compact-v2` replaces the previously published long cards at the owner's
explicit request. Cards use one action sentence, relevant changes, an optional reason,
and concise IDs. Permission updates show every changed permission on its own line,
grouped into authorized, denied and reset permissions, without bitmasks or omitted
counts. Permission groups split only at line boundaries to respect Discord fields;
the full list is exempt from the compact card length budget and batch abbreviation.
Member/voice cards have at most two fields; ordinary administrative cards at most three.
The marker is stored as embed URL metadata so the visible footer remains short.

The one-time replacement freezes full original outbox rows in
`vice_audit_replacements`, including message IDs and payloads. It checks every live
message's author and exact markers before tracked deletion; unrelated content,
attachments and components fail closed. The configured old log panel is likewise
validated, snapshotted and recreated. No broad purge is used. Missing old messages
are acknowledged, source entries are refreshed, and the compact queue resets once.
Concurrent new entries and merged updates are preserved. Restart stages prevent
deleting recreated cards or resetting delivered rows again. Original payloads and
the journal remain available for review; deleted Discord message IDs cannot be
restored. To undo presentation, deploy a revised formatter that edits the current
outbox messages. Never clear the migration state or restore an old database, which
would risk replaying cleanup or losing subsequent activity.

To stop this feature, remove its StoreBot event callbacks and ViceDistrict lifecycle
integration together; preserve the vice_audit_outbox/state tables, posted history and
journal. Never delete records as part of disabling the listener. Historical ordinary
voice sessions and voluntary departures cannot be reconstructed from Discord audit logs.

The second expression pack adds six original coquí meme faces (built-in imagegen)
and six vector/canvas GIF loops (VI neon, WEPA, alert, loading palm, hype and RIP).
All assets are 128×128 with transparency, under 256 KiB. GIFs have 20 frames and
2.4-second infinite loops. Source renderers and final prompts are in the static/animated
manifests under assets/vice-district/emojis-v2.

The third pack adds 12 original vector/canvas animated GIFs under emojis-v3: six
expressive coquí mascots (party, laughter, tears, anger, love and wave) and six
Puerto Rico/crew reactions (waving flag, DURO, GG, crown, drift and BOOM). Large
silhouettes and contrasting outlines are checked at both 128 and 32 pixels.
The fourth pack responds to feedback that those loops were too subtle: 12 `_max`
variants in emojis-v4 use full-body hops/tilts, large facial changes, travelling tears,
hand waves, falls/rebounds, spins, car travel and expanding bursts. Each has a before/after
comparison at 32 px. Existing emoji IDs and reactions are retained; Discord's guild
emoji edit endpoint cannot replace image bytes. The new variants have distinct names
and are featured first in the announcements panel.
The server now has 12 static and 30 animated emojis, plus the existing three stickers.
`vice_expressions.py` prevalidates every asset and aggregates capacity across all
packs of each format before any upload. It preserves unrelated expressions and
existing emoji IDs, with tracked writes and durable ID/release markers. The announcements
panel displays all 42 expressions. To stop further installation, revert the expression
installer and showcase release together; keep the installed emojis and their journal.

View-only panels (`vice_readonly.py`, vice-view-only-v1) deny member publication,
attachments, emoji/sticker posts, new reactions, polls, voice messages and threads.
They also deny slash/external app commands in those channels; staff can run commands
from chat-staff, while all existing bot buttons and selectors remain available.
The migration covers the 8 public information/control panels, staff log, admin-only
departures and closed tickets. It preserves every existing visibility/history/voice
permission and leaves chat channels and open tickets alone. All existing role/member
overrides receive the publication denies, with the exact bot member retained as publisher.
Server owners and Administrator naturally bypass Discord channel overwrites.
Existing reaction seeds are cleared with durable count snapshots, including threads;
a guild-scoped raw reaction handler clears any new seeds so members cannot reuse them.
No messages or histories are deleted. New installations and ticket closures use the
same overwrite policy. Revert the readonly integration to stop the guard, then restore
only publication permission bits from the journal if requested; reaction choices cannot
be recreated on behalf of other users.

Run the focused Studio regression modules and `tests.test_vice_district` with unittest.
The latter covers exact guild scope, role escalation prevention, private tickets,
preserved histories, persistent controls, duplicate welcomes and the avatar renderer.
On Windows the old Studio tests leave a few SQLite connections awaiting GC; collect
garbage before TestCase.doCleanups to release those handles without altering runtime code.

## Restoration

### Spam protection and ticket help center

`vice_antispam.py` acts only in the authorized district, excluding bots, webhooks,
the owner and current administrator/moderation/support staff. It detects 6 messages
in 8 seconds, 3 repeated texts in 15 seconds (with message-content intent), 6 distinct
user/role mentions and unauthorized global mentions. It removes only the triggering
message, warns without pinging, and records a compact private alert. A burst counts
as one incident per 10 seconds; repeat incidents within 5 minutes use 60-second then
300-second timeouts, never shortening an existing timeout. Fresh membership,
hierarchy and bot permissions are checked before action. Young accounts (under 24 h)
and arrival bursts (5 in 10 seconds) only produce private observations, never bans.
Counters/digests are bounded and in-memory; raw message contents are not journaled.
Disabling this feature means removing its message/member handlers and lifecycle;
keep audit history. Existing timeouts expire normally.

`vice_tickets.py` adds an ephemeral selection of Ayuda general, Reportar a un jugador,
Apelación and Problema técnico. One open ticket per person is retained; choosing another
category never relabels an existing conversation. The starter shows category and
responsible staff member with persistent Atender, Liberar and Cerrar y archivar buttons.
Assignments are serialized under the ticket lock and persisted before panel updates;
only the current assignee or an administrator can release an assignment. Restart
recovery repairs the exact registered panel. Closing preserves the assignment and
history and removes its open controls.

`vice_ticket_archive.py` creates a registered, private, read-only archivo-tickets
channel in Equipo for the owner, administrator, moderation and support roles. Before
confirmed deletion, it saves a ZIP containing escaped static HTML, JSON and the actual
Discord attachment bytes under `/data/vice-ticket-archives`, then uploads it privately
and downloads it again to verify its SHA-256. Current ticket content and destination
permissions are checked again before deletion. Failed downloads, changed content,
missing content intent, unexpected access, threads or excessive size keep the source
ticket intact. Limits: 10,000 messages, 200 attachments, 25 MiB each, 100 MiB attachments
total and 20 MiB transcript data; the final ZIP must also fit the guild upload limit.
No public storage is used. A frozen, one-time list of existing closed tickets receives
copies without deleting the sources. Receipts and exact fingerprints prevent duplicate
uploads; missing sources are recorded as unavailable rather than recreated.

To revert the help center, restore the previous opener and starter views together,
keeping ticket rows, assignments and panel receipts. To disable deletion safely,
remove its controls; do not bypass the required backup check. Keep the archive channel,
ZIP files and receipts as private records. Original Discord IDs cannot be restored.

### Ticket assignment notices and private feedback

New assignments publish one concise notice inside the registered private ticket,
permitting a notification only to that ticket's owner. A persisted assignment revision
and exact bot message marker recover interrupted sends without duplicate notices.
Existing assignments are not notified retroactively. Failure to send never undoes
the assigned responsible member. A bounded worker retries pending notices every
60 seconds, and shutdown cancels it cleanly.

`vice_ticket_feedback.py` freezes category, owner and assignee at closure and adds
an author-only 1–5 rating form with an optional comment. The selector and modal are
private; only an explicit submission creates a rating. One durable response is allowed
per ticket, and current guild, member, source panel and closed-ticket scope are checked.
Responses are delivered without pings to the registered administration-only
`valoraciones` channel in Equipo, with the same publication restrictions as other
view-only panels. Moderation and support cannot view responses through their roles.
Pending deliveries survive restarts; ratings remain retained after ticket deletion.
An independent worker retries up to 20 pending deliveries per pass every 60 seconds.
Comments never appear in the ticket or its staff archive copy. Disabling the feature
requires removing its notice/close hooks and feedback control together, preserving
ratings, closure snapshots and delivery receipts. Do not replay old notifications,
delete feedback history or create demonstration ratings on the live server.

### Country, region and platform roles

The optional role catalog includes the 18 Spanish-speaking Latin American states
plus Puerto Rico, eight overlapping regional identity tags, and four platform
choices: three supported options plus PC explicitly marked as waiting. This replaces the wider Caribbean/device catalog following the
owner's explicit correction. Puerto Rico comes first.
The old Preferences divider retains its ID and becomes Platforms. Countries,
Regions and Alerts each receive a separate divider. Existing roles and member
assignments are preserved; all added roles are cosmetic with zero permissions.

`vice_optional_roles.py` applies only its versioned catalog migration, using
journaled before-states and durable creation nonces with exact audit recovery.
It does not replay base/staff installation or modify welcome/ticket permissions.
The country selector allows one choice among 19 options. Regions,
platforms and alerts remain independent, multi-select groups. Every selection
fetches current roles and member data; managed, protected or privileged roles
are rejected. Staff/rank roles remain manually assigned. The four controls stay
in `elige-tus-roles`; none is added to the welcome panel.

To disable, remove the optional migration hook and adapt the roles panel together.
Keep the role registry, creation receipts and member assignments. Do not delete
roles or replay a full installation as a rollback. The explicit Hispanic-scope
correction retires only frozen registered unused cosmetic roles, retaining receipts
and before-states. Grouped numeric positions handle Discord's role-position ties
without moving the bot or staff hierarchy. The platform choices are PS5, Xbox
Series X|S and Xbox One (Cloud Gaming), checked against Rockstar's current support
page on November 18, 2026. The owner explicitly requested keeping PC in Platforms;
its existing ID and assignments are preserved, and its label says Esperando GTA VI.
No PC version is represented as confirmed.

### Closed ticket deletion controls

`vice_ticket_delete.py` adds the persistent red **Eliminar** button to registered
closed VIce District tickets, including existing archive messages. Obsolete close
controls are removed only from recognized bot ticket panels in that closed ticket.
Setup never deletes a ticket. The owner, administrators, moderators and support may
request deletion; the bot freshly verifies membership and staff roles, then shows
an ephemeral confirmation tied to that actor and channel. A second check under the
ticket lock requires the exact guild, persisted closed state, archive category and
owner topic before deleting. The confirmation explicitly states that the channel
and its messages will be deleted. Cancelling leaves the ticket unchanged.

Deletion retains the ticket row as deleted and a durable before-state of channel
configuration, access and ticket identity. This is an audit record, not a promise
to restore Discord messages or attachments. A persisted deletion attempt permits
narrow 404 reconciliation after an interrupted acknowledgement. Startup only
installs controls or reconciles a proven missing ticket; it never initiates deletion.
To disable the control, remove TicketDeletion lifecycle integration and the close
hook, keeping its receipts and ticket rows. Already deleted Discord channels cannot
recover their original IDs.

Keep the Railway `/data` volume and both SQLite databases. To disable only the new
community runtime, remove the `ViceDistrict` integration from store_bot.py and revert
studio_guard.py to the original single-guild allowlist, then deploy the restored code.
Do not delete the new Discord channels or their histories. The new journal's bot_changes
table contains the original roles, positions, permissions and channel overwrites for
review if the owner requests a layout rollback. Never apply that snapshot to another guild.
