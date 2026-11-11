"""Daily availability announcement; the live monitor remains independent."""
from zoneinfo import ZoneInfo
import discord
from bot_settings import DEFAULTS,friendly_hour,parse_hour

PR_TZ = ZoneInfo("America/Puerto_Rico")
SLOT_KEY = "daily_server_up_slot"


async def announce_daily_up(now, state, confirmed_state, maintenance, get_setting,
                            set_setting, send):
    """Check only the configured PR minute, without replaying missed announcements.

    Called under the monitor lock. Reserve the date before sending so a restart
    or an ambiguous webhook timeout cannot send the same announcement twice.
    An unavailable server consumes today's slot without publishing anything.
    """
    local = now.astimezone(PR_TZ)
    hour,minute=map(int,parse_hour(get_setting('daily_server_up_time','18:30')).split(':'))
    if (local.hour, local.minute) != (hour,minute):
        return "outside_schedule"
    if get_setting('panel.announcements.daily_enabled','1')!='1':return 'disabled'
    slot = local.date().isoformat()
    if get_setting(SLOT_KEY, "") >= slot:
        return "already_checked"
    available = state == "up" and confirmed_state == "up" and not maintenance
    set_setting(SLOT_KEY, slot)
    if not available:
        return "skipped_unavailable"
    await send()
    return "sent"


def daily_up_embed(get_setting,connect_url):
    values={key:get_setting(key,default) for key,default in DEFAULTS.items()}
    data=dict(enlace=connect_url,servidor='La Venganza RP',hora=friendly_hour(values['daily_server_up_time']))
    embed=discord.Embed(title=values['daily_server_up_title'].format_map(data),
        description=values['daily_server_up_body'].format_map(data),color=0xE53935)
    embed.set_footer(text=values['daily_server_up_footer'].format_map(data))
    return embed
