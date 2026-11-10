"""The official report questions, kept together in one Discord modal."""
import re
import unicodedata

DETAILS_LIMIT=3500
SECTIONS=[('description','Descripción del error','Describe qué sucede'),
          ('steps','Cómo ocurrió','Indica paso a paso qué estabas haciendo'),
          ('system','Sistema afectado','Inventario, vehículos, trabajos, scripts u otro'),
          ('frequency','Frecuencia','Siempre, a veces o una sola vez')]

def key(text):
    text=''.join(c for c in unicodedata.normalize('NFKD',text).casefold() if c.isalnum())
    return re.sub(r'^\d+','',text)

ALIASES={key(label):field for field,label,_ in SECTIONS}
ALIASES.update({key(label):field for field,labels in {
    'description':['Qué pasa','Descripción'], 'steps':['Cómo ocurrió el error','Cómo pasó','Pasos para reproducirlo'],
    'system':['Dónde pasa','Sistema'], 'frequency':['Cada cuánto pasa','Con qué frecuencia ocurre']}.items() for label in labels})

def details_default(data):
    if data.get('report_schema')==4 and data.get('details'):return data['details']
    values=dict(data)
    if data.get('details'):values['description']=data['details']
    return '\n\n'.join(f'{label}:\n{values.get(field) or "["+placeholder+"]"}' for field,label,placeholder in SECTIONS)

def parse_details(text):
    sections={};current=None
    for line in text.splitlines():
        heading,colon,answer=line.partition(':')
        field=ALIASES.get(key(heading)) if colon else None
        if field:
            if field in sections:raise ValueError('Cada apartado debe aparecer una sola vez en los detalles.')
            current=field;sections[field]=[answer.strip()]
        elif current:sections[current].append(line)
        elif line.strip():raise ValueError('Completa los cuatro apartados conservando sus títulos: descripción, cómo ocurrió, sistema y frecuencia.')
    result={field:'\n'.join(lines).strip() for field,lines in sections.items()}
    placeholders={key('['+hint+']') for _,_,hint in SECTIONS}
    missing=[label for field,label,_ in SECTIONS if not result.get(field) or key(result[field]) in placeholders]
    if missing:raise ValueError('Falta completar: '+', '.join(missing)+'. Reemplaza el texto entre corchetes con tu respuesta.')
    for field,limit in [('description',1500),('steps',1200),('system',160),('frequency',100)]:
        if len(result[field])>limit:raise ValueError(f'El apartado «{next(label for name,label,_ in SECTIONS if name==field)}» es demasiado largo; usa hasta {limit} caracteres.')
    return result

def panel_embed():
    import discord
    embed=discord.Embed(title='🐛 Reportes de errores · La Venganza RP',color=0xBE2335,
        description='Informa de un fallo del servidor desde **Reportar un error**. El formulario reúne los datos y el clip en una sola ventana; al enviarlo, podrás revisar la información antes de publicarla.')
    embed.add_field(name='👤 1. Identificación',value='Tu **cuenta de Discord** se registra automáticamente. Escribe también tu **ID dentro del servidor** para que el equipo pueda identificarte.',inline=False)
    embed.add_field(name='🐛 2. Nombre y detalles del error',value='Escribe un **título breve** y completa los cuatro apartados del formulario:\n\n**Descripción:** qué sucede y qué debería suceder.\n**Cómo ocurrió:** pasos y acciones anteriores al fallo.\n**Sistema afectado:** inventario, vehículos, trabajos, scripts u otro.\n**Frecuencia:** siempre, a veces o una sola vez.',inline=False)
    embed.add_field(name='🎥 3. Clip obligatorio',value='**Adjunta el video en el formulario o pega el enlace del clip.** Debe mostrar claramente el problema y, si es posible, cómo repetirlo.\n\n**Sin clip no se permite publicar el reporte.**',inline=False)
    embed.add_field(name='📋 4. Revisión y seguimiento',value='Comprueba los datos antes de publicar. Cada error tendrá su propia publicación, un responsable y un historial de cambios.\n\n🔴 Pendiente → 🟠 En revisión → 🔵 En proceso → 🟢 Solucionado\n⚫ Cerrado: reporte finalizado, incompleto o duplicado.',inline=False)
    embed.add_field(name='Antes de enviar',value='Un reporte por error. Continúa en tu publicación si ya lo enviaste. No compartas contraseñas ni datos personales. **Owner, Programador y administradores** gestionan la revisión.',inline=False)
    embed.set_footer(text='La Venganza RP · Equipo de desarrollo · Panel oficial de reportes')
    return embed
