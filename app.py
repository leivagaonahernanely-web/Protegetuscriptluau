from flask import Flask, render_template, redirect, url_for, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from authlib.integrations.flask_client import OAuth
import os, hashlib, random, string

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'clave_secreta_123456')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
oauth = OAuth(app)

discord = oauth.register(
    name='discord',
    client_id=os.getenv('DISCORD_CLIENT_ID', ''),
    client_secret=os.getenv('DISCORD_CLIENT_SECRET', ''),
    authorize_url='https://discord.com/api/oauth2/authorize',
    access_token_url='https://discord.com/api/oauth2/token',
    userinfo_endpoint='https://discord.com/api/users/@me',
    client_kwargs={'scope': 'identify'}
)

class Key(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(32), unique=True, nullable=False)
    discord_id = db.Column(db.String(20))
    hwid = db.Column(db.String(64))
    active = db.Column(db.Boolean, default=True)

with app.app_context():
    db.create_all()

@app.route('/')
def inicio():
    return "<h1>🛡️ ProtectorScript</h1><br><a href='/login'>🔑 Iniciar sesión con Discord</a>"

@app.route('/login')
def login():
    return discord.authorize_redirect(url_for('callback', _external=True))

@app.route('/callback')
def callback():
    usuario = discord.get('https://discord.com/api/users/@me').json()
    return f"<h2>Bienvenido {usuario['username']}</h2><p>Tu ID: {usuario['id']}</p>"

@app.route('/api/verify', methods=['POST'])
def verificar():
    datos = request.get_json()
    if not datos:
        return jsonify({"ok": False, "mensaje": "Sin datos"})
    clave = datos.get("key")
    hwid = datos.get("hwid")
    if not clave or not hwid:
        return jsonify({"ok": False, "mensaje": "Falta clave o HWID"})
    registro = Key.query.filter_by(key=clave, active=True).first()
    if not registro:
from flask import Flask, render_template, redirect, url_for, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from authlib.integrations.flask_client import OAuth
from flask_cors import CORS
import os, hashlib, random, string

app = Flask(__name__)
CORS(app)

# Configuración
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'clave_secreta_muy_larga_123456')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///keys.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['DISCORD_CLIENT_ID'] = os.getenv('DISCORD_CLIENT_ID')
app.config['DISCORD_CLIENT_SECRET'] = os.getenv('DISCORD_CLIENT_SECRET')
app.config['RAILWAY_URL'] = os.getenv('RAILWAY_URL')

db = SQLAlchemy(app)
oauth = OAuth(app)

# Conexión con Discord
discord = oauth.register(
    name='discord',
    client_id=app.config['DISCORD_CLIENT_ID'],
    client_secret=app.config['DISCORD_CLIENT_SECRET'],
    authorize_url='https://discord.com/api/oauth2/authorize',
    access_token_url='https://discord.com/api/oauth2/token',
    userinfo_endpoint='https://discord.com/api/users/@me',
    client_kwargs={'scope': 'identify openid'},
    server_metadata_url=None
)

# Modelo de claves
class Key(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(32), unique=True, nullable=False)
    discord_id = db.Column(db.String(20))
    hwid = db.Column(db.String(64))
    active = db.Column(db.Boolean, default=True)

# Crear tablas al iniciar
with app.app_context():
    db.create_all()

# Ruta principal
@app.route('/')
def inicio():
    return """
    <h1>🛡️ ProtectorScript</h1>
    <p>Sistema de verificación de acceso</p>
    <br>
    <a href="/login" style="padding:10px 20px; background:#5865F2; color:white; border-radius:5px; text-decoration:none;">🔑 Iniciar sesión con Discord</a>
    """

# Iniciar sesión
@app.route('/login')
def login():
    redirect_uri = f"{app.config['RAILWAY_URL']}/callback"
    return discord.authorize_redirect(redirect_uri)

# Volver de Discord
@app.route('/callback')
def callback():
    try:
        token = discord.authorize_access_token()
        usuario = discord.get('https://discord.com/api/users/@me').json()
        return f"""
        <h2>✅ Bienvenido {usuario['username']}#{usuario['discriminator']}</h2>
        <p>Tu ID de Discord: {usuario['id']}</p>
        <br>
        <a href="/">Volver al inicio</a>
        """
    except Exception as e:
        return f"<h2>❌ Error: {str(e)}</h2><br><a href='/'>Volver</a>"

# Verificar clave desde el script
@app.route('/api/verify', methods=['POST'])
def verificar():
    datos = request.get_json()
    if not datos:
        return jsonify({"ok": False, "mensaje": "Sin datos recibidos"})
    clave = datos.get("key")
    hwid = datos.get("hwid")
    if not clave or not hwid:
        return jsonify({"ok": False, "mensaje": "Falta clave o HWID"})
    registro = Key.query.filter_by(key=clave, active=True).first()
    if not registro:
        return jsonify({"ok": False, "mensaje": "Clave inválida o desactivada"})
    hwid_hash = hashlib.sha256(hwid.encode()).hexdigest()
    if not registro.hwid:
        registro.hwid = hwid_hash
        db.session.commit()
        return jsonify({"ok": True, "mensaje": "✅ Clave activada correctamente"})
    if registro.hwid == hwid_hash:
        return jsonify({"ok": True, "mensaje": "✅ Acceso permitido"})
    else:
        return jsonify({"ok": False, "mensaje": "❌ HWID no coincide"})

# Generar clave nueva
@app.route('/api/generar', methods=['POST'])
def generar_clave():
    nueva_clave = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=16))
    db.session.add(Key(key=nueva_clave))
    db.session.commit()
    return jsonify({"clave": nueva_clave})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
