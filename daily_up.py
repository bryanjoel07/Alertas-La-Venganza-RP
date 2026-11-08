"""Daily availability announcement; the live monitor remains independent."""
from zoneinfo import ZoneInfo

PR_TZ = ZoneInfo("America/Puerto_Rico")
SLOT_KEY = "daily_server_up_slot"


async def announce_daily_up(now, state, confirmed_state, maintenance, get_setting,
                            set_setting, send):
    """Check only the 18:30 PR minute, without replaying missed announcements.

    Called under the monitor lock. Reserve the date before sending so a restart
    or an ambiguous webhook timeout cannot send the same announcement twice.
    An unavailable server consumes today's slot without publishing anything.
    """
    local = now.astimezone(PR_TZ)
    if (local.hour, local.minute) != (18, 30):
        return "outside_schedule"
    slot = local.date().isoformat()
    if get_setting(SLOT_KEY, "") >= slot:
        return "already_checked"
    available = state == "up" and confirmed_state == "up" and not maintenance
    set_setting(SLOT_KEY, slot)
    if not available:
        return "skipped_unavailable"
    await send()
    return "sent"
