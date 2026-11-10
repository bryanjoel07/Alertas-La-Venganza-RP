"""Topic explanations explicitly requested by the owner, separate from quoted rules."""
from dataclasses import dataclass

from rules_search import ALIASES,STOP,normalize

TICKETS_CHANNEL=1513423707467415642


@dataclass(frozen=True)
class RuleTopic:
 key:str
 heading:str
 body:str


TOPICS={
 'ck':RuleTopic('ck','CK · Muerte definitiva del personaje',
  '**CK significa Character Kill.**\n\n'
  '**¿Qué es?**\n'
  'Es el final de la historia de tu personaje. Muere de forma definitiva y ya no puedes seguir roleando con él.\n\n'
  '**¿Qué pasa después?**\n'
  'Se pierde el progreso de ese personaje dentro del rol, incluidos sus bienes, su dinero y sus contactos. '
  'Si quieres seguir jugando, creas otro personaje con otra historia.\n\n'
  '**¿Cuándo se plantea?**\n'
  'Puede plantearse por un acuerdo fuera del personaje (OOC) o por una situación importante de la historia, '
  'como una traición dentro de una organización.\n\n'
  '**¿Cómo se solicita en La Venganza?**\n'
  f'Abre un ticket en <#{TICKETS_CHANNEL}>. Administración revisa el caso y confirma si se aprueba y bajo qué condiciones.'),
 'pkt':RuleTopic('pkt','PKT · Pérdida total de memoria',
  '**PKT significa Player Kill Total.**\n\n'
  '**¿Qué es?**\n'
  'Es la pérdida total de los recuerdos relacionados con el conflicto o la etapa que se acuerde para ese PKT. '
  'Tu personaje sigue vivo y puedes seguir usando su mismo cuerpo y nombre.\n\n'
  '**¿Qué tiene que olvidar?**\n'
  'Los hechos, las personas, los lugares y la información relacionados con esa parte de su historia. '
  'Después no puede usar esos recuerdos para continuar el conflicto o delatar a quienes participaron.\n\n'
  '**Ejemplo**\n'
  'Una organización te captura y, dentro de un rol aprobado, te «borra el cassette». '
  'Después no recuerdas quiénes eran, dónde estabas ni qué pasó durante esa situación.\n\n'
  '**¿Cómo se solicita en La Venganza?**\n'
  f'Abre un ticket en <#{TICKETS_CHANNEL}>. Administración revisa el caso y deja claro qué parte de la historia debe olvidar el personaje.'),
}


def topic_for(query):
 value=normalize(query)
 ignored=STOP|{'significa','significado','definicion','explica','explicar','explicacion','concepto'}
 value=' '.join(token for token in value.split() if token not in ignored)
 return next((topic for key,topic in TOPICS.items() if value in ALIASES[key]),None)
