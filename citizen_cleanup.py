"""One owner's request: keep Ciudadanos on two exact accounts, once."""

import asyncio
import json
import logging
import os

import discord

from photo_members import MemberDirectory

log = logging.getLogger("LaVenganzaRP.roles")
GUILD_ID = 1244988345327550565
BOT_ID = 1567658433497399408
CITIZEN_ID = 1245009164070158409
REQUEST = "esschino-citizen-20261110-v1"
RETRY_REQUEST = "esschino-citizen-20261110-v2"
ENV = "CITIZEN_CLEANUP_REQUEST_ID"
TARGETS = ("esschino__", "esschino_")
ROLE_SLOTS = ("color", "titulo")


def resolve_targets(members):
    targets = []
    for name in TARGETS:
        matches = [m for m in members if m.name.casefold() == name]
        if len(matches) != 1 or matches[0].bot:
            raise ValueError(f"No hay una sola cuenta válida con el usuario exacto {name}.")
        targets.append(matches[0])
    return targets


def assigned_ids(member):
    # Member.roles uses the gateway role cache; _roles preserves all IDs from REST.
    return set(member._roles) - {GUILD_ID}


def member_state(member, roles):
    ids = assigned_ids(member)
    if ids - roles.keys():
        raise ValueError("Discord devolvió un rol que no figura en la lista actual.")
    return dict(user_id=member.id, username=member.name,
                roles=[dict(id=rid, name=roles[rid].name) for rid in sorted(ids)])


def role_assignable(role, top, can_manage):
    return can_manage and not role.managed and role < top


async def keep_citizen_roles(bot):
    request = os.getenv(ENV, "").strip()
    if request not in (REQUEST, RETRY_REQUEST):
        return
    if bot.user.id != BOT_ID:
        raise ValueError("Esta solicitud pertenece al bot de La Venganza RP.")
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        raise ValueError("No encuentro La Venganza RP.")
    # Also exclude a concurrent automatic cosmetic recovery while removing roles.
    async with bot.citizen_cleanup_lock, bot.economy.delivery.lock:
        journal = bot.changes.journal
        key = f"operation:{ENV}:{request}"
        existing = await asyncio.to_thread(journal.by_key, key)
        if existing and existing["status"] == "completado":
            log.info("CITIZEN_CLEANUP already_completed request=%s", request)
            return json.loads(existing["after_json"])

        source = existing
        if request == RETRY_REQUEST and not source:
            source = await asyncio.to_thread(journal.by_key, f"operation:{ENV}:{REQUEST}")
            if not source:
                raise ValueError("El reintento necesita la copia original de las dos cuentas.")

        store = bot.economy.store

        def equipped(uid):
            return store.rows("SELECT * FROM eco_equipped WHERE user_id=? AND slot IN ('color','titulo') ORDER BY slot", (uid,))

        if source:
            plan = json.loads(source["before_json"])["plan"]
        else:
            directory = MemberDirectory(bot, GUILD_ID)
            targets = resolve_targets(await directory.load(guild, force=True))
            roles = {r.id: r for r in await guild.fetch_roles()}
            plan = dict(request=REQUEST, guild_id=GUILD_ID, citizen_id=CITIZEN_ID,
                        targets=[])
            for found in targets:
                member = await guild.fetch_member(found.id)
                if member.name != found.name or member.bot:
                    raise ValueError("El usuario cambió mientras se comprobaba su cuenta.")
                state = member_state(member, roles)
                state["equipped"] = equipped(member.id)
                plan["targets"].append(state)

        if (plan["request"] != REQUEST or plan["guild_id"] != GUILD_ID
                or plan["citizen_id"] != CITIZEN_ID
                or sorted(t["username"] for t in plan["targets"]) != sorted(TARGETS)
                or len({t["user_id"] for t in plan["targets"]}) != 2):
            raise ValueError("La copia de esta solicitud no corresponde a las dos cuentas autorizadas.")

        result = {}

        async def snapshot():
            roles = {r.id: r for r in await guild.fetch_roles()}
            states = []
            for target in plan["targets"]:
                member = await guild.fetch_member(target["user_id"])
                state = member_state(member, roles)
                state["equipped"] = equipped(member.id)
                states.append(state)
            return dict(request=request, plan=plan, members=states, result=result)

        async def apply():
            for target in plan["targets"]:
                roles = {r.id: r for r in await guild.fetch_roles()}
                citizen = roles.get(CITIZEN_ID)
                if citizen is None or citizen.managed:
                    raise ValueError("No encuentro el rol Ciudadanos esperado.")
                me = await guild.fetch_member(BOT_ID)
                mine = [roles[rid] for rid in assigned_ids(me) | {GUILD_ID}]
                top = max(mine)
                can_manage = any(r.permissions.administrator or r.permissions.manage_roles for r in mine)
                administrator = any(r.permissions.administrator for r in mine)
                log.info("CITIZEN_CLEANUP permissions administrator=%s manage_roles=%s top_role=%s top_role_id=%s top_position=%s request=%s",
                         administrator, can_manage, top.name, top.id, top.position, request)
                member = await guild.fetch_member(target["user_id"])
                if member.bot:
                    raise ValueError("Una cuenta autorizada no puede ser un bot.")
                blocked = []
                if CITIZEN_ID not in assigned_ids(member):
                    if not role_assignable(citizen, top, can_manage):
                        raise ValueError("El bot no puede asignar Ciudadanos; no se quitaron sus otros roles.")
                    await member.add_roles(citizen, atomic=True, reason="Solicitud del dueño: conservar Ciudadanos")

                # Unequip only role cosmetics from the saved plan so recovery cannot
                # regrant them. Purchases, coins and other profile items stay intact.
                for row in target["equipped"]:
                    if row["slot"] not in ROLE_SLOTS or row["user_id"] != member.id:
                        raise ValueError("Equipamiento fuera del alcance de esta solicitud.")
                    store.rows("DELETE FROM eco_equipped WHERE user_id=? AND slot=? AND purchase_id=? AND value=?",
                               (member.id, row["slot"], row["purchase_id"], row["value"]))

                # Never extend a saved request to roles assigned after it started.
                original = {r["id"] for r in target["roles"]} - {CITIZEN_ID}
                for rid in sorted(original & assigned_ids(member)):
                    role = roles[rid]
                    # The owner explicitly renewed this exact membership request.
                    # On v2 let Discord make the final decision, without editing
                    # any role's permissions or hierarchy. Managed roles stay out.
                    if role.managed or (request != RETRY_REQUEST and not role_assignable(role, top, can_manage)):
                        blocked.append(dict(id=rid, name=role.name, reason="managed" if role.managed else "hierarchy_or_permission"))
                        continue
                    try:
                        await member.remove_roles(role, atomic=True,
                            reason="Solicitud del dueño: dejar solo Ciudadanos en sus dos cuentas")
                        log.info("CITIZEN_CLEANUP removed user=%s id=%s role=%s role_id=%s", target["username"], member.id, role.name, rid)
                    except discord.HTTPException as exc:
                        blocked.append(dict(id=rid, name=role.name, reason=f"discord_{exc.status}_{exc.code}",
                                            role_position=role.position, bot_top_position=top.position))
                        log.warning("CITIZEN_CLEANUP discord_rejected user_id=%s role_id=%s role=%s status=%s code=%s role_position=%s bot_top_position=%s administrator=%s",
                                    member.id, rid, role.name, exc.status, exc.code, role.position, top.position, administrator)
                fresh_roles = {r.id: r for r in await guild.fetch_roles()}
                fresh = await guild.fetch_member(member.id)
                verified = member_state(fresh, fresh_roles)
                verified["only_citizen"] = assigned_ids(fresh) == {CITIZEN_ID}
                verified["blocked"] = blocked
                result[str(member.id)] = verified
                log.info("CITIZEN_CLEANUP verified %s", json.dumps(verified, ensure_ascii=False))

        await bot.changes.tracked(ENV, "Dejar Ciudadanos en las dos cuentas del dueño", apply,
                                  request_id=request, snapshot=snapshot)
        log.info("CITIZEN_CLEANUP finished request=%s only_citizen=%s", request,
                 all(r["only_citizen"] for r in result.values()))
        return result
