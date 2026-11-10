"""One owner-requested correction; never enforce a priority on later restarts."""
import logging
import time

GUILD_ID=1244988345327550565
BOT_ID=1567658433497399408
TICKET_ID=5
CHANNEL_ID=1569527961718358088
REQUEST_KEY='priority-repair:ticket-5-alta-20261110'
# Do not overwrite a staff change made after this repair was prepared.
REQUEST_CUTOFF=1794337979
log=logging.getLogger('LaVenganzaRP.tickets')


async def repair_requested_priority(system):
 if system.guild_id!=GUILD_ID or system.bot.user.id!=BOT_ID:return
 if system.store.config(REQUEST_KEY)=='complete':return
 async with system.case_lock(TICKET_ID):
  async with system.lock:
   row=system.store.get(TICKET_ID)
   if not row or row['channel']!=CHANNEL_ID or row.get('deleted_at') or row['status'] not in ('nuevo','en_atencion','esperando_jugador','resuelto'):
    log.info('TICKETS priority_repair_skipped ticket=%s reason=case_unavailable',TICKET_ID)
    system.store.config(REQUEST_KEY,'complete');return
   event=system.store.priority_event(TICKET_ID)
   if event and event['created']>REQUEST_CUTOFF:
    await system.refresh(row,verify_priority=True)
    system.store.config(REQUEST_KEY,'complete')
    log.info('TICKETS priority_repair_skipped ticket=%s reason=newer_priority_change current=%s',TICKET_ID,system.store.get(TICKET_ID)['priority'])
    return

   async def snapshot():
    current=system.store.get(TICKET_ID)
    channel=await system.channel(current)
    message=await channel.fetch_message(current['control_message'])
    if message.author.id!=BOT_ID:raise ValueError('El panel del ticket no pertenece al bot esperado.')
    return dict(ticket=current,priority_event=system.store.priority_event(TICKET_ID),message=message.id,
      embeds=[embed.to_dict() for embed in message.embeds],components=[c.to_dict() for c in message.components])

   async def correct():
    log.info('TICKETS priority_repair_observed ticket=%s stored=%s requested=alta',TICKET_ID,system.store.get(TICKET_ID)['priority'])
    # The snapshot can await Discord. Recheck the event before writing anything.
    latest=system.store.priority_event(TICKET_ID)
    if not latest or latest['created']<=REQUEST_CUTOFF:
     await system.call('set_priority',TICKET_ID,'alta',BOT_ID,'Solicitud del propietario: corregir el panel para que muestre Alta.')
    await system.refresh(system.store.get(TICKET_ID),verify_priority=True)

   await system.bot.changes.tracked('TICKET_PRIORITY_REPAIR','Corregir la prioridad solicitada para el ticket #5',correct,
     request_id=f'{REQUEST_KEY}:{time.time_ns()}',snapshot=snapshot)
   system.store.config(REQUEST_KEY,'complete')
   log.info('TICKETS priority_repair_verified ticket=%s stored=%s displayed_verified=True one_shot=True',TICKET_ID,system.store.get(TICKET_ID)['priority'])
