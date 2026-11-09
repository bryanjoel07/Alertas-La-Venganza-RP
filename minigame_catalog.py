"""Question bank. Photos are original generated recreations, not game captures."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ASSETS=ROOT/'assets'/'minigames'
KINDS={'foto':'Adivinar lugar','roleplay':'Roleplay','acertijo':'Acertijos'}

ROLEPLAY=[
 ('¿Cómo se llama usar información de Discord que tu personaje no sabe?','Metagaming',['mg','meta gaming'],'Es metagaming: tu personaje no sabe todo lo que tú lees fuera del juego.'),
 ('Obligas a otro personaje a perder, sin darle oportunidad de responder al rol. ¿Qué estás haciendo?','Powergaming',['pg','power gaming'],'El otro jugador también debe poder responder a lo que ocurre.'),
 ('Matas a otro personaje sin ningún motivo de rol. ¿Cómo se llama?','RDM',['random deathmatch','random death match','deathmatch','dm'],'RDM es matar sin un motivo de rol que lo justifique.'),
 ('Usas un carro para atropellar jugadores sin motivo de rol. ¿Cómo se llama?','VDM',['vehicle deathmatch','vehicle death match'],'VDM es usar un vehículo para matar sin una razón de rol.'),
 ('Te desconectas para evitar una detención que ya está ocurriendo. ¿Cómo se llama?','Combat logging',['combat log','combatlog','combatlogging','evadir rol','evasión de rol'],'Salir para escapar de una situación de rol es evadirla.'),
 ('¿Qué significan las siglas IC?','Dentro del personaje',['in character','dentro de personaje','en personaje','dentro del rol'],'IC es lo que ocurre como tu personaje dentro del mundo del juego.'),
 ('¿Qué significan las siglas OOC?','Fuera del personaje',['out of character','fuera de personaje','fuera del rol'],'OOC es la conversación fuera de tu personaje.'),
 ('Vuelves a buscar a quien te mató solo para vengarte, usando lo que recuerdas fuera del rol. ¿Cómo se llama?','Revenge kill',['rk','revenge killing','revengekill'],'No debes usar recuerdos que tu personaje perdió para ir a vengarte.'),
 ('Tu personaje ignora por completo que le están apuntando con un arma. ¿Qué rol está faltando?','Fear RP',['fearrp','rol de miedo','valorar la vida','valoración de vida','valorar su vida'],'Tu personaje debe reaccionar al peligro y valorar su vida.'),
 ('Descubres un fallo del juego y lo usas para sacar ventaja. ¿Cómo se llama?','Abuso de bugs',['bug abuse','bug abusear','abusar de bugs','explotar bugs','bug exploit','exploit'],'Aprovechar un fallo para ganar una ventaja es abuso de bugs.'),
 ('¿Cómo se llama manejar con saltos y golpes imposibles, como si el carro no sufriera daños?','Conducción antirrol',['conduccion antirol','conduccion irreal','manejo antirrol','non rp driving','fail driving'],'Conducir también forma parte del rol: el carro y sus ocupantes sufren consecuencias.'),
 ('Hablas de Discord o de un reinicio como si tu personaje conociera esas cosas. ¿Qué estás mezclando?','IC y OOC',['ic ooc','ooc e ic','ic con ooc','ooc con ic','mezclar ic y ooc','mixing','mezcla ic ooc'],'Estás mezclando información de fuera del personaje con lo que ocurre dentro del rol.'),
 ('Provocas a la policía sin motivo de rol solo para que te persiga. ¿Cómo se llama?','Cop baiting',['copbaiting','cop bait','bait a la policia','provocar a la policia'],'Buscar una persecución sin motivo de rol se conoce como cop baiting.'),
 ('Ves lo que otro jugador está haciendo en su directo y vas a buscarlo con esa información. ¿Cómo se llama?','Stream sniping',['streamsniping','stream snipe','streamsnip'],'Usar un directo para localizar a otro jugador es stream sniping y también usa información OOC.'),
 ('¿Qué significa RP?','Roleplay',['role play','juego de rol','rol'],'Roleplay es interpretar un personaje y actuar según su historia y lo que le pasa.'),
 ('¿A dónde debes llevar una queja para que el staff la revise sin cortar una escena de rol?','Un ticket',['ticket','tickets','soporte','abrir un ticket','al staff mediante ticket'],'Guarda lo que pasó y abre un ticket para que el equipo pueda revisarlo.'),
 ('¿Qué conviene guardar para que el staff pueda revisar lo que pasó en una escena?','Pruebas',['evidencia','evidencias','clip','clips','video','un clip','grabacion','capturas'],'Un clip o una captura con contexto ayuda a revisar el caso.'),
 ('¿Qué deberías leer antes de entrar a jugar y cuando tengas una duda sobre lo permitido?','Las reglas',['reglas','normativa','normativas','reglamento','normas','reglas del servidor'],'Las reglas del servidor son la referencia para saber qué está permitido.'),
 ('Tu personaje está herido. ¿Qué deberías rolear en vez de actuar como si nada?','Las heridas',['heridas','lesiones','dolor','las lesiones','su dolor','las consecuencias'],'Las heridas y sus consecuencias deben formar parte de lo que interpreta tu personaje.'),
 ('¿Puedes usar fuera de rol una amistad para obligar a alguien a ayudarte dentro del rol? Responde sí o no.','No',['no puedes','no se puede'],'La otra persona decide cómo actúa su personaje; una amistad no obliga a darle ventajas.'),
 ('¿Está bien pedirle a otro jugador su contraseña para ayudarlo con un ticket? Responde sí o no.','No',['no esta bien','no se debe'],'El soporte no necesita contraseñas para revisar un ticket.'),
 ('¿El saldo de la tienda de Discord es lo mismo que el dinero de tu personaje en FiveM? Responde sí o no.','No',['no es lo mismo','son distintos'],'Las monedas de la comunidad sirven para la tienda y los perfiles de Discord.'),
 ('¿Cómo se llama actuar como otra persona, con su propia historia, dentro del juego?','Interpretar un personaje',['interpretacion','interpretar','rolear','roleplay','rol','interpretacion de personaje'],'Tu personaje puede pensar y decidir distinto de como lo harías tú.'),
 ('¿Puedes usar el ID que ves sobre alguien como si tu personaje ya supiera su nombre? Responde sí o no.','No',['no puedes','no se puede'],'Un ID de juego no significa que tu personaje conozca a esa persona.'),
 ('Si un amigo rompe una regla, ¿debes darle ventaja por ser tu amigo? Responde sí o no.','No',['no debes','no se debe'],'Las reglas se aplican igual, aunque conozcas a la persona.'),
]
RIDDLES=[
 ('Cuanto más le quitas, más grande se hace. ¿Qué es?','Un agujero',['agujero','hoyo','hueco'],'Un agujero crece cuando le quitas material alrededor.'),
 ('Tiene dientes, pero no muerde. Lo usas para arreglarte el pelo. ¿Qué es?','Un peine',['peine'],'Los dientes del peine sirven para ordenar el pelo.'),
 ('Tiene agujas, pero no cose. Te dice qué hora es. ¿Qué es?','Un reloj',['reloj','reloj de agujas'],'Son las agujas del reloj.'),
 ('Está llena de agujeros y aun así guarda agua. ¿Qué es?','Una esponja',['esponja'],'Los pequeños huecos de una esponja retienen agua.'),
 ('Si la nombras, la rompes. ¿Qué es?','El silencio',['silencio'],'Al hablar rompes el silencio.'),
 ('Es tuyo, pero los demás lo usan más que tú. ¿Qué es?','Tu nombre',['nombre','mi nombre'],'Los demás dicen tu nombre para llamarte.'),
 ('Tiene ciudades sin casas, ríos sin agua y montañas sin tierra. ¿Qué es?','Un mapa',['mapa'],'Un mapa representa esos lugares con dibujos.'),
 ('Sube mientras pasan los años y nunca vuelve a bajar. ¿Qué es?','La edad',['edad','mi edad'],'La edad aumenta con el tiempo.'),
 ('Te sigue cuando hay luz, pero desaparece en la oscuridad. ¿Qué es?','Tu sombra',['sombra','mi sombra'],'La sombra se forma cuando algo tapa la luz.'),
 ('Tiene cuello, pero no cabeza; guarda agua y lleva tapa. ¿Qué es?','Una botella',['botella'],'La parte estrecha de la botella se llama cuello.'),
 ('Tiene hojas, pero no es un árbol. Cuenta una historia al leerlo. ¿Qué es?','Un libro',['libro'],'Las páginas de un libro también se llaman hojas.'),
 ('Cuanto más seca, más mojada queda. ¿Qué es?','Una toalla',['toalla'],'La toalla absorbe el agua de lo que seca.'),
 ('Tiene teclas y una barra de espacio, pero no abre ninguna puerta. ¿Qué es?','Un teclado',['teclado','teclado de computadora'],'Un teclado tiene teclas, pero no llaves.'),
 ('Tiene cuatro patas, un tablero encima y no camina. ¿Qué es?','Una mesa',['mesa'],'Las patas sostienen la mesa.'),
 ('¿Qué mes tiene por lo menos 28 días?','Todos',['todos los meses','cada mes','los doce','12','los 12 meses'],'Todos los meses tienen al menos 28 días.'),
 ('¿Qué pesa más: un kilo de hierro o un kilo de algodón?','Pesan lo mismo',['lo mismo','igual','pesan igual','ninguno','ambos pesan igual'],'Los dos pesan un kilo.'),
 ('Un carro eléctrico va hacia el norte. ¿Hacia dónde sale el humo del motor?','No sale humo',['no tiene humo','no hay humo','ningun lado','ninguna','no echa humo'],'Un carro eléctrico no tiene humo de escape del motor.'),
 ('Tiene un ojo, no ve y sirve para coser. ¿Qué es?','Una aguja',['aguja','aguja de coser'],'El agujero por donde pasa el hilo se llama ojo.'),
 ('Va de casa en casa llevando mensajes, pero siempre va pegado al sobre. ¿Qué es?','Un sello',['sello','estampilla','sello postal'],'El sello viaja pegado a la carta.'),
 ('Entra al agua, pero no se moja. Es lo que ves de ti en la superficie. ¿Qué es?','Tu reflejo',['reflejo','mi reflejo'],'La imagen reflejada no se moja.'),
 ('No tiene boca, pero repite lo que dices entre las montañas. ¿Qué es?','El eco',['eco'],'El eco es el sonido que vuelve después de rebotar.'),
 ('Tiene cama, pero no duerme; tiene corriente, pero no enchufe. ¿Qué es?','Un río',['rio'],'La cama es el cauce y la corriente es el agua que avanza.'),
 ('¿Cuántos animales de cada especie metió Moisés en el arca?','Ninguno',['ningun animal','cero','0','fue noe','noe'],'El relato del arca es de Noé, no de Moisés.'),
 ('¿Qué está siempre delante de ti, pero todavía no ha llegado?','El futuro',['futuro','mañana','manana'],'El futuro siempre está por llegar.'),
 ('Mientras más avanza, menos le queda de cera. Alumbra con una llama. ¿Qué es?','Una vela',['vela'],'La vela se consume mientras alumbra.'),
]

def load_bank(check_images=False):
 photos=json.loads((ROOT/'minigame_photos.json').read_text())
 questions=[]
 for q in photos:
  question={k:v for k,v in q.items() if k!='scene'}
  if check_images:
   image=(ASSETS/question['image']).resolve()
   if image.parent!=ASSETS.resolve() or not image.is_file() or not 0<image.stat().st_size<8*1024*1024:
    raise ValueError(f'Falta o no es válida la imagen {question["id"]}.')
  questions.append(question)
 for kind,items in [('roleplay',ROLEPLAY),('acertijo',RIDDLES)]:
  for n,(prompt,answer,aliases,explanation) in enumerate(items,1):
   questions.append(dict(id=f'{kind}{n:02}',kind=kind,prompt=prompt,answer=answer,aliases=[answer,*aliases],explanation=explanation))
 if len({q['id'] for q in questions})!=len(questions):raise ValueError('Hay preguntas repetidas.')
 return questions
