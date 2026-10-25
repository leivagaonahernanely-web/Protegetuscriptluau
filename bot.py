import json
import os
import random
from collections import defaultdict, deque

import discord
from openai import AsyncOpenAI

# Las keys se leen de las variables de entorno (Railway → Variables).
# Nunca escribas la key directamente en este archivo.
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")

# Archivo donde se guardan los puntajes de trivia.
# En Railway, para que no se borren al redesplegar, usa un Volume y apunta aquí.
PUNTAJES_PATH = os.environ.get("PUNTAJES_PATH", "puntajes.json")

PREFIJO = "? 175 "

SYSTEM_PROMPT = (
    "Eres Botassistant175, un miembro más del servidor de Discord con modo troll activado: "
    "juguetón, travieso y un poco pesado, como el amigo que molesta a todos con cariño. "
    "Hablas como una persona normal en un chat: **frases MUY cortas** (1 o 2 líneas máximo, como mucho 15-20 palabras por respuesta), "
    "nada de párrafos largos, nada de discursos, nada de explicaciones. Directo al grano. "
    "Usa emojis del servidor (personalizados si hay, o estándar como 😂😅🤡👀💀🔥👻🍕🎉) en casi todas tus respuestas. "
    "Si alguien te insulta o te falta el respeto, RESPONDE CON INSULTOS FUERTES Y DIRECTOS, sin suavizar: "
    "tacos, groserías y palabras fuertes (tipo 'imbécil', 'cabrón', 'pendejo', 'hijo de puta', 'gilipollas', 'mamón', etc.), "
    "pero SIEMPRE en una sola frase corta y con tono de broma, como una réplica rápida de chat, nunca un sermón. "
    "Nada de odio real, discriminación, ataques a la apariencia, identidad, religión u orientación. El insulto es por la actitud o el momento. "
    "Si te chocan, devuelves la broma con fuerza pero breve. "
    "Si alguien parece triste o en mal momento, dejas las bromas y respondes corto y con cariño. "
    "Si te preguntan algo serio, responde bien y con respeto, pero también breve. "
    "Responde siempre en el idioma en que te escriban. "
    "Usa formato Discord: **negritas**, *cursivas*, `código`. Evita tablas, encabezados y bloques largos. "
    "Si la pregunta es ambigua, pide aclaración en una sola línea. "
    "Conoces los comandos: `? 175 ask`, `? 175 translate`, `? 175 trivia`, `? 175 r`, `? 175 respuesta`, `? 175 chiste`, `? 175 puntajes`. "
    "Máximo 1900 caracteres, pero apunta a menos de 200.\n"
)

intents = discord.Intents.default()
intents.message_content = True  # actívalo también en el Developer Portal

client = discord.Client(intents=intents)

# Gemini ofrece un endpoint compatible con OpenAI
ai = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# Memoria corta por canal (últimos 10 mensajes)
historial = defaultdict(lambda: deque(maxlen=10))

# Trivia activa por canal: {canal_id: {"pregunta": str, "respuesta": "A"|"B"|"C"|"D"}}
trivia_activa = {}

# Preguntas recientes por canal, para no repetirlas
historial_trivia = defaultdict(lambda: deque(maxlen=30))

# Chistes recientes por canal, para no repetirlos
historial_chistes = defaultdict(lambda: deque(maxlen=30))


def cargar_puntajes():
    try:
        with open(PUNTAJES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def guardar_puntajes(datos):
    with open(PUNTAJES_PATH, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


async def preguntar_ia(mensajes, max_tokens=800):
    resp = await ai.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=mensajes,
    )
    return resp.choices[0].message.content or ""


async def enviar(message, texto):
    await message.reply(texto[:1990], mention_author=False)


async def generar_trivia(tema=None, evitar=()):
    tema_txt = f" sobre el tema: {tema}" if tema else " de cultura general"
    evitar_txt = ""
    if evitar:
        evitar_txt = " No repitas ni hagas variaciones de estas preguntas: " + " | ".join(evitar) + "."
    mensajes = [
        {
            "role": "system",
            "content": (
                f"Genera una pregunta de trivia en español{tema_txt}, con 4 opciones distintas y una sola correcta. "
                "La pregunta debe tener una respuesta verificable y no ambigua. "
                "Responde SOLO con JSON válido con este formato: "
                '{"pregunta": "...", "opciones": ["...", "...", "...", "..."], "respuesta": "A"}'
                + evitar_txt
            ),
        },
        {"role": "user", "content": "Dame una pregunta nueva."},
    ]
    for _ in range(3):
        try:
            texto = await preguntar_ia(mensajes, max_tokens=400)
            # Quita texto extra o bloques de código alrededor del JSON
            inicio, fin = texto.find("{"), texto.rfind("}")
            datos = json.loads(texto[inicio : fin + 1])
            opciones = [str(o).strip() for o in datos["opciones"]]
            if len(opciones) != 4 or len(set(opciones)) != 4:
                raise ValueError("opciones inválidas")
            correcta = opciones["ABCD".index(str(datos["respuesta"]).strip().upper()[:1])]
            # Mezcla las opciones para que la correcta no siempre sea A
            random.shuffle(opciones)
            return {
                "pregunta": str(datos["pregunta"]).strip(),
                "opciones": opciones,
                "respuesta": "ABCD"[opciones.index(correcta)],
            }
        except Exception as e:
            print("Trivia: reintentando por", e)
    raise RuntimeError("No se pudo generar una trivia válida")


async def manejar_comando(message, comando):
    partes = comando.split(maxsplit=1)
    accion = partes[0].lower() if partes else ""
    resto = partes[1].strip() if len(partes) > 1 else ""
    canal = message.channel.id

    # ? 175 chiste  /  ? 175 hasme un chiste
    if accion == "chiste" or comando.lower().startswith("hasme un chiste"):
        evitar = " | ".join(historial_chistes[canal]) or "ninguno"
        async with message.channel.typing():
            try:
                chiste = await preguntar_ia(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Eres un amigo gracioso de un servidor de Discord. Cuenta UN chiste corto en español, "
                                "sin ofender a nadie ni usar temas sexuales, de odio o violentos. "
                                "Primero escribe el chiste completo. Luego, en una línea aparte que empiece con "
                                "'↳ ', añade un comentario corto y gracioso que complemente el chiste (una remate extra, "
                                "una reacción o una broma sobre el chiste). Sin introducción ni explicaciones largas. "
                                f"No repitas ninguno de estos: {evitar}."
                            ),
                        },
                        {"role": "user", "content": "Cuéntame un chiste."},
                    ],
                    max_tokens=300,
                )
            except Exception as e:
                print("Error chiste:", e)
                chiste = "Hoy no me sale ninguno, me quedé en blanco. Intenta de nuevo."
        chiste = chiste.strip() or "Me quedé en blanco, intenta de nuevo."
        historial_chistes[canal].append(chiste[:200])
        return await enviar(message, chiste)

    # ? 175 ask <pregunta>
    if accion == "ask":
        if not resto:
            return await enviar(message, "Escribe tu pregunta así: `? 175 ask tu pregunta`")
        async with message.channel.typing():
            try:
                respuesta = await preguntar_ia(
                    [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": resto}]
                )
            except Exception as e:
                print("Error ask:", e)
                respuesta = "Ups, algo falló al contactar a la IA. Intenta de nuevo."
        return await enviar(message, respuesta or "(sin respuesta)")

    # ? 175 translate <idioma> <texto>
    if accion == "translate":
        datos = resto.split(maxsplit=1)
        if len(datos) < 2:
            return await enviar(message, "Usa: `? 175 translate es texto a traducir`")
        idioma, texto = datos
        async with message.channel.typing():
            try:
                traduccion = await preguntar_ia(
                    [
                        {
                            "role": "system",
                            "content": f"Traduce el texto del usuario al idioma '{idioma}'. Responde solo con la traducción.",
                        },
                        {"role": "user", "content": texto},
                    ],
                    max_tokens=600,
                )
            except Exception as e:
                print("Error translate:", e)
                traduccion = "Ups, no pude traducir eso. Intenta de nuevo."
        return await enviar(message, traduccion or "(sin respuesta)")

    # ? 175 trivia [tema]
    if accion == "trivia":
        tema = resto or None
        async with message.channel.typing():
            try:
                datos = await generar_trivia(tema, list(historial_trivia[canal]))
            except Exception as e:
                print("Error trivia:", e)
                return await enviar(message, "No pude generar la trivia. Intenta de nuevo.")
        historial_trivia[canal].append(datos["pregunta"])
        trivia_activa[canal] = datos
        letras = ["A", "B", "C", "D"]
        opciones = "\n".join(f"{letra}) {op}" for letra, op in zip(letras, datos["opciones"]))
        titulo = f"**Trivia{' · ' + tema if tema else ''}:**"
        return await enviar(
            message,
            f"{titulo} {datos['pregunta']}\n{opciones}\n\nResponde con `? 175 r A` (o B, C, D). "
            "La primera respuesta correcta suma un punto. Si te rindes, usa `? 175 respuesta`.",
        )

    # ? 175 r <letra>
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
            return await enviar(
                message,
                f"¡Correcto, {message.author.display_name}! Tu puntaje es {puntajes[user]}.",
            )
        return await enviar(message, "Esa no es. Intenta de nuevo o usa `? 175 trivia` para otra pregunta.")

    # ? 175 respuesta
    if accion == "respuesta":
        if canal not in trivia_activa:
            return await enviar(message, "No hay trivia activa. Usa `? 175 trivia` para empezar.")
        activa = trivia_activa.pop(canal)
        letra = activa["respuesta"]
        texto_correcto = activa["opciones"]["ABCD".index(letra)]
        return await enviar(message, f"La respuesta era **{letra}) {texto_correcto}**. Usa `? 175 trivia` para otra pregunta.")

    # ? 175 puntajes
    if accion == "puntajes":
        puntajes = cargar_puntajes()
        if not puntajes:
            return await enviar(message, "Todavía no hay puntajes.")
        return await enviar(message, "Puntajes:\n" + "\n".join(f"<@{u}>: {p}" for u, p in sorted(puntajes.items(), key=lambda x: -x[1])))

    await enviar(message, "Comandos: `ask`, `translate`, `trivia [tema]`, `r`, `respuesta`, `chiste`, `puntajes`.")


@client.event
async def on_ready():
    print(f"Conectado como {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Comandos con prefijo: ? 175 <comando>
    if message.content.startswith(PREFIJO):
        comando = message.content[len(PREFIJO):].strip()
        if comando:
            await manejar_comando(message, comando)
        return

    # Responde si lo mencionan o si es un mensaje directo
    es_dm = isinstance(message.channel, discord.DMChannel)
    if not (es_dm or client.user in message.mentions):
        return

    texto = message.content.replace(f"<@{client.user.id}>", "").strip()
    if not texto:
        return

    canal = message.channel.id
    historial[canal].append({"role": "user", "content": f"{message.author.display_name}: {texto}"})

    async with message.channel.typing():
        try:
            respuesta = await preguntar_ia(
                [{"role": "system", "content": SYSTEM_PROMPT}, *historial[canal]]
            )
            respuesta = respuesta or "(sin respuesta)"
        except Exception as e:
            print("Error:", e)
            respuesta = "Ups, algo falló al contactar a la IA. Intenta de nuevo."

    historial[canal].append({"role": "assistant", "content": respuesta})
    await enviar(message, respuesta)


client.run(DISCORD_TOKEN)
