import logging
import json
from pathlib import Path
import discord
from feedback_ui import reply, NONE, RED
from bug_store import STATES

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
        self.upload_limit=min(25*1024*1024,getattr(system.bot.get_guild(system.guild_id),'filesize_limit',25*1024*1024))
        self.step=1 if row['step']!=1 else 2
        super().__init__(title=f'Reportar un error · {self.step}/2',timeout=900)
        data=json.loads(row['data']);self.inputs={}
        if self.step==1:
            for key,label,limit,paragraph in [('player_id','Tu ID dentro del servidor',30,False),('title','¿Qué error encontraste?',100,False),
                ('description','¿Qué está pasando?',1200,True),('steps','¿Qué estabas haciendo cuando pasó?',1000,True),('system','¿Dónde pasa? Inventario, carros, trabajo…',100,False)]:
                item=discord.ui.TextInput(label=label,max_length=limit,default=data.get(key),style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short)
                self.inputs[key]=item;self.add_item(item)
        else:
            self.frequency=discord.ui.Select(options=[discord.SelectOption(label=v,value=v) for v in ('Siempre','A veces','Una sola vez')])
            self.clip=discord.ui.TextInput(required=False,max_length=1000,placeholder='https://…',default=data.get('clip'))
            self.file=discord.ui.FileUpload(custom_id='clip_file',required=False,min_values=0,max_values=1)
            self.add_item(discord.ui.Label(text='¿Cada cuánto pasa?',component=self.frequency))
            self.add_item(discord.ui.Label(text='Enlace del clip (si lo tienes)',component=self.clip))
            self.add_item(discord.ui.Label(text='O adjunta el video aquí',description=f'Video de hasta {self.upload_limit//(1024*1024)} MB. Hace falta un archivo o un enlace.',component=self.file))
    async def on_submit(self,i):
        await i.response.defer(ephemeral=True,thinking=True)
        try:
            await self.system.member(i)
            if self.step==1:
                from feedback import clean
                await self.system.call('save',self.rid,i.user.id,1,{k:clean(v.value) for k,v in self.inputs.items()},self.revision)
                await reply(i,'Guardé los datos del error, bro. Falta el clip y revisar antes de publicarlo.',view=buttons('continue',rid=self.rid))
            else:
                filename=video=None
                if self.file.values:
                    attachment=self.file.values[0]
                    filename=Path(attachment.filename).name[:100]
                    if attachment.size>self.upload_limit or Path(filename).suffix.lower() not in ('.mp4','.webm','.mov','.m4v'):
                        raise ValueError(f'Adjunta un video MP4, WEBM o MOV de hasta {self.upload_limit//(1024*1024)} MB. Si pesa más, pega su enlace.')
                    video=await attachment.read()
                values=dict(frequency=self.frequency.values[0] if self.frequency.values else '',clip=self.clip.value)
                await self.system.call('save',self.rid,i.user.id,2,values,self.revision,filename,video)
                row=await self.system.call('get',self.rid)
                await reply(i,'**Revisa tu reporte. Se publicará en el foro para que lo vea la comunidad.**\nEvita contraseñas y datos personales.',embed=self.system.embed(row),view=buttons('publish','continue',rid=self.rid))
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
