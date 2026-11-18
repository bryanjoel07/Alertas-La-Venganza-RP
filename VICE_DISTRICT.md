# GTA VI Latino | VIce District

Owner-authorized community release: `vice-district-community-v3`, 2026-11-17.
The welcome panel has no role menu or role-menu button, as explicitly requested.
Role selections live only in their dedicated channel (and the optional /vice roles command).
Guild: `1572462544302383164`. Bot: `1571639486591402174` (EssChino Studio Bot).

The existing Studio guild retains its handlers, store layout and `/data/esschino.sqlite3`.
VIce District uses a separate `/data/vice-district.sqlite3`, exact guild and owner checks,
its own command group `/vice`, persistent component IDs prefixed `vice:v1:` and welcome receipts.

The layout contains six categories and 21 permanent channels: arrival, community,
GTA discussion, voice, support and private staff. There are 20 human roles (including
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
It never deletes roles, channels or messages. Every configuration operation, role change,
ticket operation and automatic welcome goes through ChangeLog.tracked with durable
before/after state. Informational panels are pinned and recovered by their bot-authored
footer markers if a deployment is interrupted.

## Validation

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
