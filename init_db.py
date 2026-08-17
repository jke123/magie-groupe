"""
Script à exécuter UNE SEULE FOIS en local, avant le premier déploiement,
pour créer les tables sur Neon et l'utilisateur admin.

Utilisation :
    1. pip install -r requirements.txt
    2. Créer un fichier .env avec DATABASE_URL=... (copié depuis Neon)
    3. python init_db.py
"""

import os
from dotenv import load_dotenv
load_dotenv()

from app import app, db, User, Setting
from werkzeug.security import generate_password_hash

with app.app_context():
    db.create_all()
    print("✅ Tables créées sur la base de données")

    if not User.query.filter_by(username='admin').first():
        # ⚠️ CHANGEZ CE MOT DE PASSE JUSTE APRÈS LA PREMIÈRE CONNEXION
        admin = User(
            username='admin',
            password_hash=generate_password_hash('MagieGroupe2025!')
        )
        db.session.add(admin)
        print("✅ Compte admin créé (username: admin / password: MagieGroupe2025!)")
        print("⚠️  CHANGEZ CE MOT DE PASSE DÈS VOTRE PREMIÈRE CONNEXION ADMIN")

    default_settings = {
        'site_name': 'Magie Groupe',
        'phone': '',
        'email': '',
        'address': '',
        'whatsapp': '',
        'instagram': '',
        'facebook': '',
        'tiktok': '',
        'meta_description': 'Magie Groupe - Production audiovisuelle et boutique en ligne'
    }
    for key, value in default_settings.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value))

    db.session.commit()
    print("✅ Paramètres par défaut créés")
    print("\n🎉 Initialisation terminée. Vous pouvez déployer sur Vercel.")
