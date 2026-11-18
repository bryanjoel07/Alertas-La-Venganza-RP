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

The second expression pack adds six original coquí meme faces (built-in imagegen)
and six vector/canvas GIF loops (VI neon, WEPA, alert, loading palm, hype and RIP).
All assets are 128×128 with transparency, under 256 KiB. GIFs have 20 frames and
2.4-second infinite loops. Source renderers and final prompts are in the static/animated
manifests under assets/vice-district/emojis-v2.

The third pack adds 12 original vector/canvas animated GIFs under emojis-v3: six
expressive coquí mascots (party, laughter, tears, anger, love and wave) and six
Puerto Rico/crew reactions (waving flag, DURO, GG, crown, drift and BOOM). Large
silhouettes and contrasting outlines are checked at both 128 and 32 pixels.
The server now has 12 static and 18 animated emojis, plus the existing three stickers.
`vice_expressions.py` prevalidates every asset and aggregates capacity across all
packs of each format before any upload. It preserves unrelated expressions and
existing emoji IDs, with tracked writes and durable ID/release markers. The announcements
panel displays all 30 expressions. To stop further installation, revert the expression
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

Keep the Railway `/data` volume and both SQLite databases. To disable only the new
community runtime, remove the `ViceDistrict` integration from store_bot.py and revert
studio_guard.py to the original single-guild allowlist, then deploy the restored code.
Do not delete the new Discord channels or their histories. The new journal's bot_changes
table contains the original roles, positions, permissions and channel overwrites for
review if the owner requests a layout rollback. Never apply that snapshot to another guild.
