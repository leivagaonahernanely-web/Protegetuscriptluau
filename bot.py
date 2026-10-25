import json
import os
from collections import defaultdict, deque

import discord
from openai import AsyncOpenAI

# Las keys se leen de las variables de entorno (Railway → Variables).
# Nunca escribas la key directamente en este archivo.
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")

# Archivo donde se guardan los puntajes de trivia.
# En Railway, para que no se borren al redesplegar, usa un Volume y apunta aquí.
PUNTAJES_PATH = os.environ.get("PUNTAJES_PATH", "puntajes.json")

PREFIJO = "? 175 "

SYSTEM_PROMPT = (
    "Eres un asistente útil y amable dentro de un servidor de Discord. "
    "Responde en el idioma del usuario, de forma clara y concisa. "
    "Tus respuestas no deben superar los 1900 caracteres."
)

intents = discord.Intents.default()
intents.message_content = True  # actívalo también en el Developer Portal

client = discord.Client(intents=intents)

# Groq usa un API compatible con OpenAI
ai = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

# Memoria corta por canal (últimos 10 mensajes)
historial = defaultdict(lambda: deque(maxlen=10))

# Trivia activa por canal: {canal_id: {"pregunta": str, "respuesta": "A"|"B"|"C"|"D"}}
trivia_activa = {}


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


async def generar_trivia():
    texto = await preguntar_ia(
        [
            {
                "role": "system",
                "content": (
                    "Genera una pregunta de cultura general en español con 4 opciones (A, B, C, D). "
                    "Responde SOLO con JSON válido con este formato: "
                    '{"pregunta": "...", "opciones": ["...", "...", "...", "..."], "respuesta": "A"}'
                ),
            },
            {"role": "user", "content": "Dame una pregunta nueva."},
        ],
        max_tokens=400,
    )
    # Quita texto extra o bloques de código alrededor del JSON
    inicio, fin = texto.find("{"), texto.rfind("}")
    return json.loads(texto[inicio : fin + 1])


async def manejar_comando(message, comando):
    partes = comando.split(maxsplit=1)
    accion = partes[0].lower() if partes else ""
    resto = partes[1].strip() if len(partes) > 1 else ""
    canal = message.channel.id

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

    # ? 175 trivia
    if accion == "trivia":
        async with message.channel.typing():
            try:
                datos = await generar_trivia()
            except Exception as e:
                print("Error trivia:", e)
                return await enviar(message, "No pude generar la trivia. Intenta de nuevo.")
        trivia_activa[canal] = {"pregunta": datos["pregunta"], "respuesta": datos["respuesta"].upper()}
        letras = ["A", "B", "C", "D"]
        opciones = "\n".join(f"{letra}) {op}" for letra, op in zip(letras, datos["opciones"]))
        return await enviar(
            message,
            f"**Trivia:** {datos['pregunta']}\n{opciones}\n\nResponde con `? 175 r A` (o B, C, D). "
            "La primera respuesta correcta suma un punto.",
        )

    # ? 175 r <letra>
    if accion == "r":
        if canal not in trivia_activa:
            return await enviar(message, "No hay trivia activa. Usa `? 175 trivia` para empezar.")
        letra = resto.upper()[:1]
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

    # ? 175 puntajes
    if accion == "puntajes":
        puntajes = cargar_puntajes()
        if not puntajes:
            return await enviar(message, "Todavía no hay puntajes.")
        return await enviar(message, "Puntajes:\n" + "\n".join(f"<@{u}>: {p}" for u, p in sorted(puntajes.items(), key=lambda x: -x[1])))

    await enviar(message, "Comandos: `ask`, `translate`, `trivia`, `r`, `puntajes`.")


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
