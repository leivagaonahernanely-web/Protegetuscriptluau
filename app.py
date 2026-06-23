from flask import Flask, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import os, hashlib, random

app = Flask(__name__)
CORS(app)

# Configuración
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'clave_segura_123456')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///keys.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Modelo de claves
class Key(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(32), unique=True, nullable=False)
    hwid = db.Column(db.String(64))
    active = db.Column(db.Boolean, default=True)

with app.app_context():
    db.create_all()

# Página principal
@app.route('/')
def inicio():
    return """
    <h1>🛡️ ProtectorScript</h1>
    <p>Sistema de verificación de claves</p>
    <br>
    <p>API lista para usar</p>
    """

# Verificar clave
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
        return jsonify({"ok": True, "mensaje": "✅ Clave activada"})
    return jsonify({"ok": registro.hwid == hwid_hash, "mensaje": "✅ Acceso permitido" if registro.hwid == hwid_hash else "❌ HWID no coincide"})

# Generar clave
@app.route('/api/generar', methods=['GET'])
def generar():
    nueva = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=16))
    db.session.add(Key(key=nueva))
    db.session.commit()
    return jsonify({"clave": nueva})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
