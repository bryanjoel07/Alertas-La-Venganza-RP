"""Public outcome notices contain no staff resolution or archive information."""
import html
import re
FINAL_STATES = {'resuelto', 'cerrado'}


def notice_kind(content, rid):
    if content.startswith('🔒 Ticket cerrado.') or content.startswith(f'🔒 Ticket #{rid} ha sido cerrado.'):
        return 'cerrado'
    if content.startswith('✅ Solución:') or content.startswith(f'✅ Ticket #{rid} ha sido resuelto.'):
        return 'resuelto'
    return None


def outcome_text(row, *, status=None, rating=True):
    status = status or row['status']
    emoji, label = ('🔒', 'cerrado') if status == 'cerrado' else ('✅', 'resuelto')
    text = f"{emoji} Ticket #{row['id']} ha sido {label}."
    if rating:
        if status=='cerrado':
            text+='\n📄 **Autor del ticket:** puedes descargar tu transcripción.'
        text += ('\n⭐ Puedes valorar la atención recibida con el botón de abajo.'
            if row.get('rating') is None else '\nGracias por valorar la atención recibida.')
        if status=='cerrado':text+='\n🗑️ **Staff autorizado:** puede eliminar el ticket.'
    return text


def saved_member_transcript(saved, row, bot_id):
    """Retain older saved conversations when structured messages are unavailable."""
    solution = '<p>Solución: ' + html.escape(row.get('resolution') or 'Sin solución registrada') + '</p>'
    text = (saved or '').replace(solution, '')
    return re.sub(r'<article><h3>[^<]* · ' + re.escape(str(bot_id)) + r'</h3>.*?</article>',
        '', text, flags=re.DOTALL)
