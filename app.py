from flask import Flask, render_template, redirect, url_for, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from authlib.integrations.flask_client import OAuth
import os, hashlib, random, string

app = Flask(__name__)
app.config['SECRET_KEY'] = "clave_secreta_larga_aleatoria_12345"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
oauth = OAuth(app)

discord = oauth.register(
    name='discord',
    client_id=os.getenv("DISCORD_CLIENT_ID", ""),
    client_secret=os.getenv("DISCORD_CLIENT_SECRET", ""),
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
    return "<h1>🛡️ Tu Sistema de Protección</h1><br><a href='/login'>🔑 Iniciar sesión con Discord</a>"

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
        return jsonify({"ok": False, "mensaje": "Clave inválida"})
    hwid_hash = hashlib.sha256(hwid.encode()).hexdigest()
    if not registro.hwid:
        registro.hwid = hwid_hash
        db.session.commit()
        return jsonify({"ok": True, "mensaje": "✅ Clave activada correctamente"})
    return jsonify({"ok": registro.hwid == hwid_hash, "mensaje": registro.hwid == hwid_hash and "✅ Acceso permitido" or "❌ HWID no coincide"})

@app.route('/api/generar', methods=['POST'])
def generar_clave():
    nueva_clave = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=16))
    db.session.add(Key(key=nueva_clave))
    db.session.commit()
    return jsonify({"clave": nueva_clave})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
