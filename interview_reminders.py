"""Timing and content for interviews scheduled by staff recruitment."""

START_GRACE_SECONDS = 600


def reminder_phase(at, now, advance_minutes):
    remaining = at - now
    advance = advance_minutes * 60
    if remaining > advance or remaining < -START_GRACE_SECONDS:
        return None
    if remaining <= 0:
        return 'hora'
    if advance > 900 and remaining <= 900:
        return 'pronto'
    return 'previo'


def notice_key(at, generation, phase='confirmada'):
    prefix = 'entrevista' if phase in {'confirmada', 'dm_cerrado'} else 'recordatorio'
    base = f'{prefix}:{at}:v{generation}'
    return base if phase == 'confirmada' else f'{base}:{phase}'


def notice_details(kind):
    parts = kind.split(':')
    if parts[0] not in {'entrevista', 'recordatorio'}:
        return None
    try:
        at = int(parts[1])
        generation = None
        phase = 'confirmada' if parts[0] == 'entrevista' else 'previo'
        if len(parts) != 2:
            if len(parts) not in (3, 4) or not parts[2].startswith('v'):
                raise ValueError
            generation = int(parts[2][1:])
            if len(parts) == 4:
                phase = parts[3]
            elif parts[0] == 'recordatorio':
                raise ValueError
        allowed = {'confirmada', 'dm_cerrado'} if parts[0] == 'entrevista' else {'previo', 'pronto', 'hora'}
        if phase not in allowed:
            raise ValueError
        return {'at': at, 'generation': generation, 'phase': phase}
    except (ValueError, IndexError):
        raise ValueError('Aviso de entrevista inválido.') from None


def interview_text(row, user, phase='confirmada', instructions=''):
    candidate = user == row['owner']
    if phase == 'confirmada':
        intro = 'Bro, tu entrevista para entrar al staff quedó agendada.' if candidate else f'Agendaste una entrevista con <@{row["owner"]}>.'
    elif phase == 'hora':
        intro = 'Bro, ya es hora de tu entrevista para el staff. 🎙️' if candidate else f'Ya es hora de tu entrevista con <@{row["owner"]}>. 🎙️'
    else:
        intro = 'Bro, recuerda tu entrevista para entrar al staff.' if candidate else f'Recuerda que tienes una entrevista con <@{row["owner"]}>.'
    text = f'{intro}\n\n📅 **Cuándo:** <t:{row["interview_at"]}:F> (<t:{row["interview_at"]}:R>).\n🎙️ **Dónde:** Sala Entrevista.'
    if candidate:
        text += '\nTen tu micrófono listo. La hora se ajusta a la de tu dispositivo.'
    if instructions.strip():
        text += '\n\n' + instructions.strip()
    return text
