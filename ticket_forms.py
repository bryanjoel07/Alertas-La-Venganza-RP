"""The questions players see for each kind of ticket."""
from dataclasses import dataclass
import re

@dataclass(frozen=True)
class Question:
 key:str
 label:str
 hint:str=''
 limit:int=1000
 required:bool=True
 paragraph:bool=False

FORMS={
 'soporte':(
  Question('help','¿Con qué necesitas ayuda?','El juego, Discord, el bot...',100),
  Question('problem','¿Qué te está pasando?','Cuéntanos qué pasa cuando lo intentas.',paragraph=True),
  Question('since','¿Desde cuándo te pasa?','Hoy, desde ayer, después de entrar...',150),
  Question('tried','¿Qué has intentado para arreglarlo?','Si no has probado nada, puedes dejarlo vacío.',required=False,paragraph=True),
  Question('proof','¿Tienes alguna captura o video?','Puedes dejar un enlace o mandarlo en el ticket.',required=False,paragraph=True)),
 'jugador':(
  Question('person','¿A quién quieres reportar?','Pon su nombre o su ID del juego.',100),
  Question('what','¿Qué pasó?','Cuéntanos lo que hizo esa persona.',paragraph=True),
  Question('when','¿Cuándo y dónde pasó?','Pon el día, la hora y el lugar si los recuerdas.',200),
  Question('proof','¿Tienes pruebas o alguien que lo haya visto?','Deja un enlace o dinos quién lo vio. Las capturas las puedes mandar luego.',required=False,paragraph=True),
  Question('discord_id','Su ID de Discord, si lo tienes','Solo números. Si no lo sabes, déjalo vacío.',20,False)),
 'tienda':(
  Question('item','¿Con qué compra necesitas ayuda?','Pon el nombre de lo que compraste.',120),
  Question('problem','¿Qué salió mal?','No te llegó, te llegó otra cosa, no te deja usarlo...',paragraph=True),
  Question('received','¿Qué compraste y qué recibiste?','Dinos qué esperabas recibir y qué tienes ahora.',paragraph=True),
  Question('when','¿Cuándo lo compraste?','El día o la hora, aunque sea más o menos.',150),
  Question('proof','¿Tienes captura del problema?','Deja un enlace o mándala después de abrir el ticket.',required=False,paragraph=True)),
 'donacion':(
  Question('type','¿Qué tipo de donación quieres hacer?','Dinero, algo para el server, otra cosa...',100),
  Question('what','¿Qué quieres donar?','Cuéntanos qué tienes en mente.',800,True,True),
  Question('how_much','¿Cuánto quieres donar?','Escribe la cantidad que tienes en mente.',100),
  Question('how','¿Cómo quieres hacerlo?','Si no sabes cómo, dinos y te ayudamos.',200),
  Question('extra','¿Quieres decirnos algo más?','Puedes dejarlo vacío.',800,False,True)),
 'apelacion':(
  Question('punishment','¿Qué castigo te pusieron?','Un ban, un aviso, cárcel...',150),
  Question('who_when','¿Quién te lo puso y cuándo?','Pon el nombre y el día, si los sabes.',200),
  Question('what','¿Qué pasó antes del castigo?','Cuéntanos tu parte de lo que pasó.',paragraph=True),
  Question('why','¿Por qué crees que deberían quitarlo?','Explícanos por qué quieres que lo revisemos.',paragraph=True),
  Question('proof','¿Tienes algo que lo demuestre?','Deja un enlace o manda las pruebas después.',required=False,paragraph=True)),
 'faccion':(
  Question('type','¿Es por una ganga o por un negocio?','Ganga o negocio.',100),
  Question('name','¿Cómo se llama?','El nombre de tu ganga o negocio.',100),
  Question('role','¿Qué haces tú ahí?','Dueño, líder, miembro...',150),
  Question('help','¿Qué necesitas?','Cuéntanos qué quieres pedir o cambiar.',paragraph=True),
  Question('extra','¿Hay algo más que debamos saber?','Puedes dejarlo vacío.',required=False,paragraph=True)),
 'staff':(
  Question('person','¿A quién del staff quieres reportar?','Pon su nombre.',100),
  Question('what','¿Qué pasó con esa persona?','Cuéntanos lo que pasó.',paragraph=True),
  Question('when','¿Cuándo pasó?','El día y la hora, si los recuerdas.',200),
  Question('proof','¿Tienes alguna prueba?','Deja un enlace o manda las capturas en el ticket.',required=False,paragraph=True),
  Question('discord_id','Su ID de Discord, si lo tienes','Solo números. Si no lo sabes, déjalo vacío.',20,False)),
}


def submission(department,answers,user):
 questions=FORMS[department]
 cleaned={}
 for question in questions:
  value=answers.get(question.key,'').strip()
  if question.required and not value:raise ValueError(f'Te falta responder: {question.label}')
  if len(value)>question.limit:raise ValueError(f'Acorta un poco esta respuesta: {question.label}')
  cleaned[question.key]=value
 excluded=None
 value=cleaned.get('discord_id','')
 if value:
  if not re.fullmatch(r'\d{17,20}',value):raise ValueError('Ese ID no parece ser de Discord. Pon solo los números o deja ese campo vacío.')
  excluded=int(value)
  if excluded==user:raise ValueError('No puedes ponerte a ti mismo como la persona reportada.')
 if department=='soporte':subject=cleaned['help']
 elif department=='jugador':subject='Reporte: '+cleaned['person']
 elif department=='staff':subject='Reporte al staff: '+cleaned['person']
 elif department=='tienda':subject='Compra: '+cleaned['item']
 elif department=='donacion':subject='Donación: '+cleaned['type']
 elif department=='apelacion':subject='Revisar castigo: '+cleaned['punishment']
 else:subject=cleaned['name']+': '+cleaned['help']
 form={q.label:cleaned[q.key] for q in questions if cleaned[q.key]}
 return subject[:100],form,excluded
