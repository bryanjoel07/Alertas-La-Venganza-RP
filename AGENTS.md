# EssChino Studio — independent bot

The active entry point is `main.py` -> `store_bot.py`. The inherited RP modules are reference code and must never be imported or started by this service.

The owner additionally authorized GTA VI Latino | VIce District (1572462544302383164) on 2026-11-17, using the same bot 1571639486591402174. Only that guild and the existing Studio guild 1514871828189941881 are allowed. Keep their handlers, layouts and durable data isolated; VIce District uses /data/vice-district.sqlite3. Never access or modify La Venganza RP (1244988345327550565), its bot (1567658433497399408), members, roles, channels, webhooks, database or deployments. This service uses its own token and /data/esschino.sqlite3 in its separate Railway project. The old bot runs from the main branch; this bot deploys only the esschino-bot branch.

The original Studio layout requirements below apply only to the Studio guild. VIce District has its own community layout, optional roles and personalized welcome cards in vice_district.py. No channels or roles in either guild may be deleted by the new community setup.

Preserve channel 1514871828672151573 and its history, make it private for the owner and new bot, and keep it in Equipo. The owner explicitly authorizes deleting the other five original channels and removing the exact empty categories left by the interrupted setup, after a durable before-state. Never extend those frozen deletion lists to later channels or repeat a completed installation.

The requested static layout has exactly five categories and eighteen channels from esschino.CATEGORIES and CHANNELS. Do not expose economy, games, roleplay, factions, recruitment, streaming or unrelated systems. Tickets create Tickets Abiertos at position zero when first opened; closing moves the existing channel to Tickets Cerrados and preserves private access and history. Never delete customer tickets as part of setup.

Route every new administrative Discord mutation through ChangeLog.tracked in studio_journal.py, with a durable before-state. Keep the release and restoration description current. Test privacy, guild scope, the requested layout and ticket lifecycle. Never put tokens or webhook credentials in source, logs or public messages. Do not invent products, prices, purchases, reviews or automatic Tebex payment verification.
