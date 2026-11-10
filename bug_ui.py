import logging
import json
import time
from pathlib import Path
import discord
from feedback_ui import reply, NONE, RED
from bug_store import STATES,clip_url
from bug_template import DETAILS_LIMIT,details_default,parse_details
from bug_limits import MAX_CLIP_BYTES

async def failed(i,error):
    if isinstance(error,ValueError):return await reply(i,str(error))
    logging.getLogger('LaVenganzaRP.bugs').error('BUGS interaction_failed',exc_info=error)
    await reply(i,'No pude completar esa acción, bro. Revisa «Mis reportes» antes de volver a enviarlo.')

class BugAction(discord.ui.DynamicItem[discord.ui.Button],template=r'lvbug:(?P<action>new|mine|continue|publish|claim|state|history):(?P<rid>[0-9]+)'):
    def __init__(self,action,rid=0):
        label,emoji={'new':('Reportar un error','🐛'),'mine':('Mis reportes','📋'),'continue':('Seguir formulario','📝'),
            'publish':('Publicar reporte','📨'),'claim':('Tomar reporte','🙋'),'state':('Cambiar estado','🛠️'),'history':('Historial','📋')}[action]
        super().__init__(discord.ui.Button(label=label,emoji=emoji,custom_id=f'lvbug:{action}:{rid}',style=discord.ButtonStyle.primary if action in ('new','continue','publish') else discord.ButtonStyle.secondary))
        self.action,self.rid=action,rid
    @classmethod
    async def from_custom_id(cls,i,item,match):return cls(match['action'],int(match['rid']))
    async def callback(self,i):
        try:await i.client.bugs.action(i,self.action,self.rid)
        except Exception as exc:await failed(i,exc)

def buttons(*actions,rid=0):
    view=discord.ui.View(timeout=None)
    for action in actions:view.add_item(BugAction(action,rid))
    return view

class BugForm(discord.ui.Modal):
    def __init__(self,system,row):
        self.system,self.rid,self.revision=system,row['id'],row['revision']
        # Discord already checks the player's upload entitlement in its picker.
        # The guild's bot attachment limit must not reject a resolved user upload.
        self.upload_limit=MAX_CLIP_BYTES
        super().__init__(title='Reportar un error',timeout=900)
        data=json.loads(row['data']);self.inputs={}
        details=details_default(data)
        for key,label,limit,paragraph in [('player_id','Tu ID dentro del servidor',30,False),('title','Nombre del error',100,False),('details','Descripción, pasos, sistema y frecuencia',DETAILS_LIMIT,True)]:
            item=discord.ui.TextInput(custom_id=key,max_length=limit,default=(details if key=='details' else data.get(key)) or None,
                style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short)
            self.inputs[key]=item
            self.add_item(discord.ui.Label(text=label,description='Completa los cuatro apartados. Conserva sus títulos y reemplaza los textos entre corchetes.' if paragraph else None,component=item))
        self.file=discord.ui.FileUpload(custom_id='clip_file',required=False,min_values=0,max_values=1)
        self.clip=discord.ui.TextInput(custom_id='clip_link',required=False,max_length=1000,placeholder='https://…',default=data.get('clip') or None)
        self.add_item(discord.ui.Label(text='Clip obligatorio · Adjunta el video aquí',description=('Ya hay un video guardado. ' if row.get('video') else '')+f'Hasta {self.upload_limit//(1024*1024)} MB. Si Discord no te deja adjuntarlo, pega el enlace abajo.',component=self.file))
        self.add_item(discord.ui.Label(text='Enlace del clip si no adjuntas el video',description='Sin video ni enlace no se puede enviar el reporte.',component=self.clip))
    async def on_submit(self,i):
        started=time.monotonic()
        await i.response.defer(ephemeral=True,thinking=True)
        try:
            from feedback import clean
            values={key:clean(item.value) for key,item in self.inputs.items()};values['clip']=clip_url(self.clip.value)
            parse_details(values['details'])
            filename=None;attachment=None
            if self.file.values:
                attachment=self.file.values[0]
                filename=Path(attachment.filename).name[:100]
                if not 0<attachment.size<=self.upload_limit or Path(filename).suffix.lower() not in ('.mp4','.webm','.mov','.m4v'):
                    raise ValueError(f'Adjunta un video MP4, WEBM o MOV de hasta {self.upload_limit//(1024*1024)} MB. Si pesa más, pega su enlace.')
            member=await self.system.member(i)
            values['discord_username']=member.name
            if attachment is not None:
                source=dict(id=attachment.id,url=attachment.url,proxy_url=attachment.proxy_url)
                revision=await self.system.call('prepare_upload',self.rid,i.user.id,values,self.revision,source,filename,attachment.size)
                row=await self.system.call('get',self.rid,include_video=False)
                try:await self.system.preview(i,row,processing=True)
                finally:self.system.clips.launch(self.rid,revision,i,attachment)
                logging.getLogger('LaVenganzaRP.bugs').info('BUGS form_received id=%s clip_bytes=%s receipt_seconds=%.2f clip_preparation=background',self.rid,attachment.size,time.monotonic()-started)
            else:
                await self.system.call('save_full',self.rid,i.user.id,values,self.revision)
                await self.system.preview(i,await self.system.call('get',self.rid,include_video=False))
                logging.getLogger('LaVenganzaRP.bugs').info('BUGS form_received id=%s clip_bytes=0 receipt_seconds=%.2f clip_preparation=not_needed',self.rid,time.monotonic()-started)
        except Exception as exc:await failed(i,exc)
    async def on_error(self,i,error):await failed(i,error)

class StatePicker(discord.ui.View):
    def __init__(self,system,owner,rid):
        super().__init__(timeout=600);self.system,self.owner,self.rid=system,owner,rid
        select=discord.ui.Select(placeholder='Elige el nuevo estado',options=[discord.SelectOption(label=label,value=key) for key,label in STATES.items()])
        async def choose(i):
            if i.user.id!=self.owner:return await reply(i,'Esta selección no es tuya.')
            await self.system.member(i,admin=True)
            state=select.values[0]
            class Reason(discord.ui.Modal,title='Actualizar reporte'):
                value=discord.ui.TextInput(label='¿Qué se hizo o qué falta?',style=discord.TextStyle.paragraph,max_length=1500)
                async def on_submit(inner,click):
                    await click.response.defer(ephemeral=True)
                    try:await self.system.change(click,self.rid,state,inner.value.value)
                    except Exception as exc:await failed(click,exc)
            await i.response.send_modal(Reason())
        select.callback=choose;self.add_item(select)
    async def on_error(self,i,error,item):await failed(i,error)
