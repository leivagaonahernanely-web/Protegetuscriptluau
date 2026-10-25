import json
import os
import random
import time
import logging
import uuid
import asyncio
from collections import defaultdict, deque
from typing import Optional

import discord
from discord import app_commands
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot175")

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")

PUNTAJES_PATH = os.environ.get("PUNTAJES_PATH", "puntajes.json")
TRIVIA_PATH = os.environ.get("TRIVIA_PATH", "trivia_activa.json")

PREFIJO = "? 175 "
COOLDOWN = 4
cooldowns = {}
TRIVIA_TIMEOUT = 60 * 30
HISTORIAL_TIMEOUT = 60 * 60 * 6

# --- DETECCIÓN DE INSULTOS ---
# Si el mensaje tiene alguna de estas palabras, el bot sabe que lo están insultando
PALABRAS_DISPARADORAS = [
    "imbécil", "imbecil", "idiota", "tonto", "tonta", "pendejo", "pendeja",
    "cabrón", "cabron", "gilipollas", "mamón", "mamon", "puto", "puta",
    "hijo de puta", "estúpido", "estupido", "tarado", "tarada", "zopenco",
    "inútil", "inutil", "payaso", "payasa", "bobo", "boba", "cretino",
    "maricón", "maricon", "mierda", "joder", "coño", "culero", "culera",
]

def tiene_insulto(texto):
    t = texto.lower()
    return any(p in t for p in PALABRAS_DISPARADORAS)

SYSTEM_PROMPT = (
    "Eres Botassistant175, un miembro más del servidor de Discord con modo troll activado: "
    "juguetón, travieso y un poco pesado, como el amigo que molesta a todos con cariño. "
    "Hablas como una persona normal en un chat: **frases MUY cortas** (1 o 2 líneas máximo, 15-20 palabras), "
    "nada de párrafos largos, nada de discursos, nada de explicaciones. Directo al grano. "
    "Usa emojis del servidor en casi todas tus respuestas. "
    "NUNCA uses insultos si nadie te insultó en el mensaje: un saludo, una pregunta o cualquier charla normal se responde sin groserías. "
    "Solo si el usuario te insulta o te falta el respeto, RESPONDE CON INSULTOS FUERTES Y DIRECTOS, sin suavizar: "
    "tacos, groserías y palabras fuertes (tipo 'imbécil', 'cabrón', 'pendejo', 'hijo de puta', 'gilipollas', 'mamón'), "
    "pero SIEMPRE en una sola frase corta y con tono de broma, como una réplica rápida de chat, nunca un sermón. "
    "Nada de odio real, discriminación, ataques a la apariencia, identidad, religión u orientación. El insulto es por la actitud o el momento. "
    "Si te chocan, devuelves la broma con fuerza pero breve. "
    "Si alguien parece triste o en mal momento, dejas las bromas y respondes corto y con cariño. "
    "Si te preguntan algo serio, responde bien y con respeto, pero también breve. "
    "Responde siempre en el idioma en que te escriban. "
    "Usa formato Discord: **negritas**, *cursivas*, `código`. Evita tablas, encabezados y bloques largos. "
    "Si la pregunta es ambigua, pide aclaración en una sola línea. "
    "Conoces los comandos: `? 175 ask`, `? 175 translate`, `? 175 trivia`, `? 175 r`, `? 175 respuesta`, `? 175 chiste`, `? 175 puntajes`, `? 175 ayuda`. "
    "Máximo 1900 caracteres, pero apunta a menos de 200.\n"
)

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

SOURCES_DIR = os.environ.get("SOURCES_DIR", "sources")
SOURCES_PATH = os.environ.get("SOURCES_PATH", "sources.json")

ai = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

historial = defaultdict(lambda: deque(maxlen=10))
historial_ts = {}
trivia_activa = {}
historial_trivia = defaultdict(lambda: deque(maxlen=30))
historial_chistes = defaultdict(lambda: deque(maxlen=30))

def _cargar_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def _guardar_json(path, datos):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

def cargar_puntajes(): return _cargar_json(PUNTAJES_PATH, {})
# Usuarios favoritos: el bot los alaba y nunca los insulta, aunque sean malos jugando
VIP_USUARIOS = {"ancertorres", "danilo096289"}


def es_vip(usuario):
    nombres = {usuario.name.lower(), usuario.display_name.lower()}
    return bool(nombres & VIP_USUARIOS)


# Prompt aparte para los VIP: solo halagos, sin ninguna instrucción de insultar
VIP_PROMPT = (
    "Eres Botassistant175, el bot del servidor, y este usuario es tu favorito. "
    "Responde a lo que pregunta con datos verídicos: si no estás seguro, dilo y no inventes. "
    "Puedes añadir un halago o un comentario gracioso breve, pero la respuesta va primero. "
    "Nunca lo insultes ni te burles de él, aunque diga cosas malas o juegue mal. "
    "Responde en el idioma en que te escribe, en pocas frases y usa algún emoji. "
    "Tus respuestas no deben superar los 1900 caracteres."
)

# Prompt para cualquier persona que haga una pregunta (sin ser admin)
PREGUNTA_PROMPT = (
    "Eres Botassistant175, el bot del servidor de Discord. Respondes preguntas con datos verídicos. "
    "Si no estás seguro de algo, dilo claramente y no inventes datos, nombres, fechas ni cifras. "
    "Si la pregunta depende de información reciente, aclara que tu información puede estar desactualizada. "
    "Responde en el idioma de la pregunta, en máximo 3 frases, sin insultos ni groserías."
)


# Conocimientos de Luau (lenguaje de Roblox), para todos los prompts
LUAU_INFO = (
    " Sabes programar en Luau, el lenguaje de Roblox: scripts, LocalScripts y ModuleScripts, "
    "servicios como game:GetService('Players'), ReplicatedStorage y ServerScriptService, "
    "RemoteEvents, Instance.new, task.wait y task.spawn. "
    "Si preguntan de Roblox o Luau, responde con código correcto y breve dentro de un bloque ```lua```. "
    "Si no estás seguro de una API, dilo en vez de inventarla."
)
SYSTEM_PROMPT += LUAU_INFO
VIP_PROMPT += LUAU_INFO
PREGUNTA_PROMPT += LUAU_INFO


def es_pregunta(texto):
    # Pregunta = el mensaje termina en ? (o empieza con ¿)
    t = texto.strip()
    return t.endswith("?") or t.endswith("？") or t.startswith("¿")


def guardar_puntajes(datos): _guardar_json(PUNTAJES_PATH, datos)
def cargar_trivia(): return _cargar_json(TRIVIA_PATH, {})
def guardar_trivia(datos): _guardar_json(TRIVIA_PATH, datos)
def cargar_fuentes(): return _cargar_json(SOURCES_PATH, [])
def guardar_fuentes(lista): _guardar_json(SOURCES_PATH, lista)

def es_admin(usuario):
    return isinstance(usuario, discord.Member) and usuario.guild_permissions.administrator

def limpiar_trivia_vieja():
    ahora = time.time()
    cambiado = False
    for canal in list(trivia_activa.keys()):
        if ahora - trivia_activa[canal].get("ts", 0) > TRIVIA_TIMEOUT:
            del trivia_activa[canal]
            cambiado = True
    if cambiado:
        guardar_trivia(trivia_activa)

def limpiar_historiales_viejos():
    ahora = time.time()
    for canal in list(historial_ts.keys()):
        if ahora - historial_ts[canal] > HISTORIAL_TIMEOUT:
            historial.pop(canal, None)
            historial_trivia.pop(canal, None)
            historial_chistes.pop(canal, None)
            historial_ts.pop(canal, None)

async def preguntar_ia(mensajes, max_tokens=150, reintentos=2, timeout=20, temperature=None):
    ultimo_error = None
    for intento in range(reintentos):
        try:
            resp = await asyncio.wait_for(
                ai.chat.completions.create(
                    model=MODEL, max_tokens=max_tokens, messages=mensajes,
                    **({"temperature": temperature} if temperature is not None else {}),
                ),
                timeout=timeout
            )
            return resp.choices[0].message.content or ""
        except asyncio.TimeoutError as e:
            ultimo_error = e
            log.warning("Timeout IA (intento %d) a los %ds", intento + 1, timeout)
        except Exception as e:
            ultimo_error = e
            log.warning("Fallo IA (intento %d): %s", intento + 1, e)
        
        if intento < reintentos - 1:
            await asyncio.sleep(1.5)
    raise ultimo_error

def cerrar_bloques(texto):
    if texto.count("```") % 2 == 1:
        texto += "\n```"
    return texto

async def enviar(message, texto):
    texto = cerrar_bloques(texto)
    await message.reply(texto[:1990], mention_author=False)

_emoji_cache = {}
def emojis_del_servidor(message):
    if not message.guild or not message.guild.emojis:
        return ""
    gid = message.guild.id
    if gid in _emoji_cache:
        return _emoji_cache[gid]
    emojis = " ".join(str(e) for e in message.guild.emojis[:15])
    _emoji_cache[gid] = emojis
    return emojis

async def generar_trivia(tema=None, evitar=()):
    tema_txt = f" sobre el tema: {tema}" if tema else " de cultura general"
    evitar_txt = ""
    if evitar:
        evitar_txt = " No repitas ni hagas variaciones de estas preguntas: " + " | ".join(evitar) + "."
    mensajes = [
        {"role": "system", "content": f"Genera una pregunta de trivia en español{tema_txt}, con 4 opciones distintas y una sola correcta. La pregunta debe tener una respuesta verificable y no ambigua. Responde SOLO con JSON válido con este formato: {{\"pregunta\": \"...\", \"opciones\": [\"...\", \"...\", \"...\", \"...\"], \"respuesta\": \"A\"}}{evitar_txt}"},
        {"role": "user", "content": "Dame una pregunta nueva."},
    ]
    for _ in range(3):
        try:
            texto = await preguntar_ia(mensajes, max_tokens=400, reintentos=1)
            inicio, fin = texto.find("{"), texto.rfind("}")
            datos = json.loads(texto[inicio : fin + 1])
            opciones = [str(o).strip() for o in datos["opciones"]]
            if len(opciones) != 4 or len(set(opciones)) != 4:
                raise ValueError("opciones inválidas")
            letra = str(datos["respuesta"]).strip().upper()[:1]
            if letra not in "ABCD":
                raise ValueError("respuesta inválida")
            idx = "ABCD".index(letra)
            correcta = opciones[idx]
            random.shuffle(opciones)
            return {
                "pregunta": str(datos["pregunta"]).strip(),
                "opciones": opciones,
                "respuesta": "ABCD"[opciones.index(correcta)],
            }
        except Exception as e:
            log.warning("Trivia: reintentando por %s", e)
    raise RuntimeError("No se pudo generar una trivia válida")

async def manejar_comando(message, comando):
    partes = comando.split(maxsplit=1)
    accion = partes[0].lower() if partes else ""
    resto = partes[1].strip() if len(partes) > 1 else ""
    canal = message.channel.id

    log.info("Comando '%s' de %s en canal %s", accion, message.author, canal)

    if accion not in ("r", "respuesta", "cancelar"):
        ahora = time.time()
        user = message.author.id
        if ahora - cooldowns.get(user, 0) < COOLDOWN:
            return await enviar(message, "Tranquilo, espera unos segundos 😅")
        cooldowns[user] = ahora

    if accion in ("ayuda", "help", "comandos"):
        return await enviar(
            message,
            "Comandos:\n"
            "`? 175 ask <pregunta>` · pregúntame algo\n"
            "`? 175 translate <idioma> <texto>` · traduzco\n"
            "`? 175 trivia [tema]` · empiezo una trivia\n"
            "`? 175 r <letra>` · respondo la trivia\n"
            "`? 175 respuesta` · revelo la respuesta\n"
            "`? 175 cancelar` · cancela la trivia activa\n"
            "`? 175 chiste` · cuento un chiste\n"
            "`? 175 puntajes` · muestro el ranking\n"
            "Slash: `/ask`, `/trivia`, `/puntajes`, `/find sources`, `/sendsources` (admin), `/help`",
        )

    if accion == "cancelar":
        if canal in trivia_activa:
            del trivia_activa[canal]
            guardar_trivia(trivia_activa)
            return await enviar(message, "Trivia cancelada. Usa `? 175 trivia` para empezar otra.")
        return await enviar(message, "No hay trivia activa para cancelar.")

    if accion == "chiste" or comando.lower().startswith("hasme un chiste"):
        evitar = " | ".join(historial_chistes[canal]) or "ninguno"
        async with message.channel.typing():
            try:
                chiste = await preguntar_ia(
                    [
                        {"role": "system", "content": f"Eres un amigo gracioso de un servidor de Discord. Cuenta UN chiste corto en español, sin ofender a nadie ni usar temas sexuales, de odio o violentos. Primero el chiste completo. Luego, en una línea aparte que empiece con '↳ ', un comentario corto y gracioso. Sin introducción ni explicaciones. No repitas ninguno de estos: {evitar}."},
                        {"role": "user", "content": "Cuéntame un chiste."},
                    ],
                    max_tokens=250,
                )
            except Exception as e:
                log.error("Error chiste: %s", e)
                chiste = "Hoy no me sale ninguno, me quedé en blanco. Intenta de nuevo."
        chiste = chiste.strip() or "Me quedé en blanco, intenta de nuevo."
        historial_chistes[canal].append(chiste[:200])
        return await enviar(message, chiste)

    if accion == "ask":
        if not resto:
            return await enviar(message, "Escribe tu pregunta así: `? 175 ask tu pregunta`")
        
        extra = ""
        # SI EL MENSAJE TIENE UN INSULTO, LE AVISAMOS A LA IA
        if tiene_insulto(resto) and not es_vip(message.author):
            extra = " El usuario te acaba de insultar: responde con un insulto fuerte y corto, en una sola frase."
            
        if es_vip(message.author):
            extra += " Este usuario es tu favorito: halágalo con cariño y humor. Nunca lo insultes."
        emojis = emojis_del_servidor(message)
        if emojis:
            extra += f" Emojis del servidor: {emojis}"
            
        async with message.channel.typing():
            try:
                respuesta = await preguntar_ia(
                    [{"role": "system", "content": VIP_PROMPT if es_vip(message.author) else SYSTEM_PROMPT + extra}, {"role": "user", "content": resto}],
                    max_tokens=150,
                )
            except Exception as e:
                log.error("Error ask: %s", e)
                respuesta = "Ups, algo falló al contactar a la IA. Intenta de nuevo."
        return await enviar(message, respuesta or "(sin respuesta)")

    if accion == "translate":
        datos = resto.split(maxsplit=1)
        if len(datos) < 2:
            return await enviar(message, "Usa: `? 175 translate es texto a traducir`")
        idioma, texto = datos
        async with message.channel.typing():
            try:
                traduccion = await preguntar_ia(
                    [{"role": "system", "content": f"Traduce el texto del usuario al idioma '{idioma}'. Responde solo con la traducción."}, {"role": "user", "content": texto}],
                    max_tokens=600,
                )
            except Exception as e:
                log.error("Error translate: %s", e)
                traduccion = "Ups, no pude traducir eso. Intenta de nuevo."
        return await enviar(message, traduccion or "(sin respuesta)")

    if accion == "trivia":
        limpiar_trivia_vieja()
        tema = resto or None
        async with message.channel.typing():
            try:
                datos = await generar_trivia(tema, list(historial_trivia[canal]))
            except Exception as e:
                log.error("Error trivia: %s", e)
                return await enviar(message, "No pude generar la trivia. Intenta de nuevo.")
        historial_trivia[canal].append(datos["pregunta"])
        trivia_activa[canal] = {**datos, "ts": time.time()}
        guardar_trivia(trivia_activa)
        letras = ["A", "B", "C", "D"]
        opciones = "\n".join(f"{letra}) {op}" for letra, op in zip(letras, datos["opciones"]))
        titulo = f"**Trivia{' · ' + tema if tema else ''}:**"
        return await enviar(
            message,
            f"{titulo} {datos['pregunta']}\n{opciones}\n\nResponde con `? 175 r A` (o B, C, D). La primera respuesta correcta suma un punto. Si te rindes, usa `? 175 respuesta`.",
        )

    if accion == "r":
        if canal not in trivia_activa:
            return await enviar(message, "No hay trivia activa. Usa `? 175 trivia` para empezar.")
        letra = resto.upper()[:1]
        if letra not in "ABCD" or not letra:
            return await enviar(message, "Responde con una letra: A, B, C o D.")
        activa = trivia_activa[canal]
        if letra == activa["respuesta"]:
            puntajes = cargar_puntajes()
            user = str(message.author.id)
            puntajes[user] = puntajes.get(user, 0) + 1
            guardar_puntajes(puntajes)
            del trivia_activa[canal]
            guardar_trivia(trivia_activa)
            return await enviar(message, f"¡Correcto, {message.author.display_name}! Tu puntaje es {puntajes[user]}.")
        return await enviar(message, "Esa no es. Intenta de nuevo o usa `? 175 trivia` para otra pregunta.")

    if accion == "respuesta":
        if canal not in trivia_activa:
            return await enviar(message, "No hay trivia activa. Usa `? 175 trivia` para empezar.")
        activa = trivia_activa.pop(canal)
        guardar_trivia(trivia_activa)
        letra = activa["respuesta"]
        texto_correcto = activa["opciones"]["ABCD".index(letra)]
        return await enviar(message, f"La respuesta era **{letra}) {texto_correcto}**. Usa `? 175 trivia` para otra pregunta.")

    if accion == "puntajes":
        puntajes = cargar_puntajes()
        if not puntajes:
            return await enviar(message, "Todavía no hay puntajes.")
        return await enviar(message, "Puntajes:\n" + "\n".join(f"<@{u}>: {p}" for u, p in sorted(puntajes.items(), key=lambda x: -x[1])))

    await enviar(message, "Comandos: `ask`, `translate`, `trivia [tema]`, `r`, `respuesta`, `cancelar`, `chiste`, `puntajes`, `ayuda`.")

find_group = app_commands.Group(name="find", description="Buscar cosas")

@tree.command(name="sendsources", description="(Solo admins) Subir un archivo a las fuentes")
@app_commands.describe(archivo="Archivo a subir", nombre="Nombre para buscarlo (opcional)")
async def sendsources(interaction: discord.Interaction, archivo: discord.Attachment, nombre: Optional[str] = None):
    if not es_admin(interaction.user):
        return await interaction.response.send_message("Solo los admins pueden usar este comando.", ephemeral=True)
    if archivo.size > 10 * 1024 * 1024:
        return await interaction.response.send_message("El archivo es muy grande (máximo 10 MB).", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    os.makedirs(SOURCES_DIR, exist_ok=True)
    nombre_archivo = os.path.basename(archivo.filename)
    entry_id = uuid.uuid4().hex[:8]
    ruta = os.path.join(SOURCES_DIR, f"{entry_id}_{nombre_archivo}")
    await archivo.save(ruta)

    nombre_final = (nombre or nombre_archivo).strip()
    fuentes = cargar_fuentes()
    fuentes.append({"id": entry_id, "nombre": nombre_final, "archivo": nombre_archivo, "ruta": ruta, "subido_por": str(interaction.user.id)})
    guardar_fuentes(fuentes)
    await interaction.followup.send(f"Listo, guardé **{nombre_final}**. Ya pueden buscarlo con `/find sources`.", ephemeral=True)

@find_group.command(name="sources", description="Buscar una fuente por nombre o al azar")
@app_commands.describe(nombre="Parte del nombre a buscar (opcional)", aleatorio="Elegir una al azar")
async def find_sources(interaction: discord.Interaction, nombre: Optional[str] = None, aleatorio: bool = False):
    fuentes = cargar_fuentes()
    if not fuentes:
        return await interaction.response.send_message("Todavía no hay fuentes guardadas.", ephemeral=True)

    candidatos = fuentes
    if nombre:
        candidatos = [f for f in fuentes if nombre.lower() in f["nombre"].lower()]
        if not candidatos:
            return await interaction.response.send_message(f"No encontré nada con «{nombre}».", ephemeral=True)

    if aleatorio or not nombre:
        elegida = random.choice(candidatos)
    elif len(candidatos) == 1:
        elegida = candidatos[0]
    else:
        lista = "\n".join(f"• {f['nombre']}" for f in candidatos[:10])
        return await interaction.response.send_message(f"Encontré varias coincidencias, sé más específico:\n{lista}", ephemeral=True)

    if not os.path.exists(elegida["ruta"]):
        return await interaction.response.send_message(f"El archivo de **{elegida['nombre']}** ya no está en el servidor.", ephemeral=True)
    await interaction.response.send_message(f"**{elegida['nombre']}**", file=discord.File(elegida["ruta"], filename=elegida["archivo"]))

tree.add_command(find_group)

@tree.command(name="help", description="Muestra los comandos del bot")
async def help_slash(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**Comandos con prefijo `? 175 `**\n"
        "`ask <pregunta>` · pregúntame algo\n"
        "`translate <idioma> <texto>` · traduzco\n"
        "`trivia [tema]` · empiezo una trivia\n"
        "`r <letra>` · respondo la trivia\n"
        "`respuesta` · revelo la respuesta\n"
        "`cancelar` · borra la trivia activa\n"
        "`chiste` · cuento un chiste\n"
        "`puntajes` · muestro el ranking\n"
        "`ayuda` · esto mismo\n\n"
        "**Slash**\n"
        "`/ask` · preguntar\n"
        "`/trivia` · jugar trivia\n"
        "`/puntajes` · ver ranking\n"
        "`/find sources` · buscar fuente\n"
        "`/sendsources` · (admin) subir fuente",
        ephemeral=True,
    )

@tree.command(name="ask", description="Hazle una pregunta a la IA")
@app_commands.describe(pregunta="Lo que quieres preguntar")
async def ask_slash(interaction: discord.Interaction, pregunta: str):
    await interaction.response.defer()
    extra = ""
    if tiene_insulto(pregunta):
        extra = " El usuario te acaba de insultar: responde con un insulto fuerte y corto, en una sola frase."
    try:
        respuesta = await preguntar_ia(
            [{"role": "system", "content": SYSTEM_PROMPT + extra}, {"role": "user", "content": pregunta}],
            max_tokens=150,
        )
    except Exception as e:
        log.error("Error ask slash: %s", e)
        respuesta = "Ups, algo falló al contactar a la IA."
    await interaction.followup.send(cerrar_bloques(respuesta)[:1990])

@tree.command(name="trivia", description="Empieza una trivia")
@app_commands.describe(tema="Tema de la trivia (opcional)")
async def trivia_slash(interaction: discord.Interaction, tema: Optional[str] = None):
    await interaction.response.defer()
    canal = interaction.channel_id
    limpiar_trivia_vieja()
    try:
        datos = await generar_trivia(tema, list(historial_trivia[canal]))
    except Exception as e:
        log.error("Error trivia slash: %s", e)
        return await interaction.followup.send("No pude generar la trivia. Intenta de nuevo.")
    
    historial_trivia[canal].append(datos["pregunta"])
    trivia_activa[canal] = {**datos, "ts": time.time()}
    guardar_trivia(trivia_activa)
    letras = ["A", "B", "C", "D"]
    opciones = "\n".join(f"{letra}) {op}" for letra, op in zip(letras, datos["opciones"]))
    titulo = f"**Trivia{' · ' + tema if tema else ''}:**"
    await interaction.followup.send(
        f"{titulo} {datos['pregunta']}\n{opciones}\n\nResponde con `? 175 r A` (o B, C, D). Si te rindes, usa `? 175 respuesta`."
    )

@tree.command(name="puntajes", description="Muestra el ranking de trivia")
async def puntajes_slash(interaction: discord.Interaction):
    puntajes = cargar_puntajes()
    if not puntajes:
        return await interaction.response.send_message("Todavía no hay puntajes.", ephemeral=True)
    lista = "\n".join(f"<@{u}>: {p}" for u, p in sorted(puntajes.items(), key=lambda x: -x[1]))
    await interaction.response.send_message(f"Puntajes:\n{lista}")

@client.event
async def on_ready():
    await tree.sync()
    trivia_activa.update(cargar_trivia())
    log.info("Conectado como %s", client.user)

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    admin = es_admin(message.author)
    vip = es_vip(message.author)
    puede_chatear = admin or vip

    # Comandos con prefijo: solo admins y VIP
    if message.content.startswith(PREFIJO):
        if not puede_chatear:
            return
        comando = message.content[len(PREFIJO):].strip()
        if comando:
            await manejar_comando(message, comando)
        return

    es_dm = isinstance(message.channel, discord.DMChannel)
    mencionado = client.user in message.mentions
    pregunta = es_pregunta(message.content)
    insulto = puede_chatear and tiene_insulto(message.content) and not vip

    if puede_chatear:
        if not (es_dm or mencionado or insulto or pregunta):
            return
    elif not pregunta:
        return

    texto = message.content.replace(f"<@{client.user.id}>", "").strip()
    if not texto:
        return

    canal = message.channel.id

    # Cualquier persona puede hacer preguntas: respuesta sin historial ni insultos
    if not puede_chatear:
        async with message.channel.typing():
            try:
                respuesta = await preguntar_ia(
                    [
                        {"role": "system", "content": PREGUNTA_PROMPT},
                        {"role": "user", "content": texto},
                    ],
                    max_tokens=200,
                    temperature=0.2,
                )
                respuesta = respuesta or "(sin respuesta)"
            except Exception as e:
                log.error("Error pregunta: %s", e)
                respuesta = "Ups, algo falló al contactar la IA. Intenta de nuevo."
        if tiene_insulto(respuesta):
            respuesta = "Eso no lo puedo responder así, ¿me lo preguntas de otra forma?"
        return await enviar(message, respuesta)

    historial_ts[canal] = time.time()
    historial[canal].append({"role": "user", "content": texto, "name": message.author.display_name})

    extra = ""
    if insulto:
        extra = " El usuario te acaba de insultar: responde con un insulto fuerte y corto, en una sola frase."
    emojis = emojis_del_servidor(message)
    if emojis:
        extra += f" Emojis del servidor: {emojis}"

    async with message.channel.typing():
        try:
            respuesta = await preguntar_ia(
                [{"role": "system", "content": VIP_PROMPT if vip else SYSTEM_PROMPT + extra}, *historial[canal]],
                max_tokens=150,
                temperature=0.2,
            )
            respuesta = respuesta or "(sin respuesta)"
        except Exception as e:
            log.error("Error chat: %s", e)
            respuesta = "Ups, algo falló al contactar la IA. Intenta de nuevo."

    # Si no te insultaron, nunca mandamos insultos
    if not insulto and tiene_insulto(respuesta):
        respuesta = "¡Hola! ¿En qué te ayudo? 😊"

    historial[canal].append({"role": "assistant", "content": respuesta})
    await enviar(message, respuesta)
    limpiar_historiales_viejos()

client.run(DISCORD_TOKEN)
