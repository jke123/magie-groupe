import os
import ssl
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from itsdangerous import URLSafeTimedSerializer
from jinja2 import ChoiceLoader, DictLoader
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import cloudinary
import cloudinary.uploader
import stripe

from templates_data import TEMPLATES
from static_data import STATIC_FILES
from static_binary_data import STATIC_BINARY_FILES

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'),
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
)

# Les templates sont d'abord cherchés sur le disque (fonctionne en local),
# puis dans TEMPLATES embarqué en dur si le fichier n'existe pas sur le disque
# (garantit le fonctionnement sur Vercel même si le dossier templates/ n'est pas empaqueté).
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    DictLoader(TEMPLATES)
])

def embedded_static(filename):
    """Sert les fichiers statiques : d'abord depuis le disque, sinon depuis les
    modules embarqués (STATIC_FILES pour le texte CSS/JS, STATIC_BINARY_FILES
    pour les images en base64) — garantit le fonctionnement même si Vercel
    n'inclut pas le dossier static/ physiquement."""
    disk_path = os.path.join(app.static_folder, filename)
    if os.path.exists(disk_path):
        return app.send_static_file(filename)

    if filename in STATIC_FILES:
        ext = filename.rsplit('.', 1)[-1] if '.' in filename else ''
        mime = 'text/css' if ext == 'css' else 'application/javascript' if ext == 'js' else 'text/plain'
        return Response(STATIC_FILES[filename], mimetype=mime)

    if filename in STATIC_BINARY_FILES:
        import base64
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        mime_map = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                    'svg': 'image/svg+xml', 'webp': 'image/webp', 'ico': 'image/x-icon', 'gif': 'image/gif'}
        mime = mime_map.get(ext, 'application/octet-stream')
        data = base64.b64decode(STATIC_BINARY_FILES[filename])
        return Response(data, mimetype=mime)

    return "Not Found", 404

# Remplace la vue de la route 'static' déjà enregistrée automatiquement par Flask,
# plutôt que d'en créer une nouvelle (éviterait un conflit de route).
app.view_functions['static'] = embedded_static

# ==================== CONFIG GÉNÉRALE ====================
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-production')

# Base de données Postgres (Neon) — fallback SQLite en local pour tests
db_url = os.environ.get('DATABASE_URL', 'sqlite:///local.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280,
}

# ==================== SÉCURITÉ ====================
# En dev (localhost), désactiver SECURE pour tester en HTTP. En prod sur Vercel, toujours HTTPS.
app.config['SESSION_COOKIE_SECURE'] = not app.debug
app.config['SESSION_COOKIE_HTTPONLY'] = True     # inaccessible en JS (anti XSS)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'    # anti CSRF basique
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=4)

csrf = CSRFProtect(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    return response

# ==================== CLOUDINARY (stockage images) ====================
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)

# ==================== STRIPE (paiement) ====================
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

def upload_image(file):
    """Upload une image vers Cloudinary, retourne l'URL sécurisée ou None"""
    if not file or file.filename == '':
        return None
    
    # Vérifier que Cloudinary est configuré
    if not os.environ.get('CLOUDINARY_CLOUD_NAME'):
        print("⚠️  CLOUDINARY non configuré - image non uploadée")
        return None
    
    allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        print(f"❌ Extension non autorisée : {ext}")
        return None
    
    try:
        result = cloudinary.uploader.upload(file, folder="magie-groupe")
        return result.get('secure_url')
    except Exception as e:
        print(f"❌ Erreur upload Cloudinary : {e}")
        return None
def delete_image(image_url):
    """Supprime une image Cloudinary à partir de son URL"""
    if not image_url or 'cloudinary.com' not in image_url:
        return
    try:
        public_id = image_url.split('/')[-1].split('.')[0]
        cloudinary.uploader.destroy(f"magie-groupe/{public_id}")
    except Exception:
        pass

# ==================== NEWSLETTER : SMTP ====================
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', SMTP_USERNAME)
SMTP_FROM_NAME = 'Magie Groupe'

serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

db = SQLAlchemy(app)

# ==================== MODÈLES ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100))
    location = db.Column(db.String(200))
    stock = db.Column(db.Integer, default=0)
    image = db.Column(db.String(500))  # URL Cloudinary complète désormais
    featured = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))
    client = db.Column(db.String(200))
    date = db.Column(db.String(100))
    image = db.Column(db.String(500))  # URL Cloudinary complète
    video_url = db.Column(db.String(500))
    featured = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    phone = db.Column(db.String(50))
    password_hash = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ConversationMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    sender = db.Column(db.String(20), nullable=False)  # 'customer' ou 'admin'
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    customer_name = db.Column(db.String(200), nullable=False)
    customer_email = db.Column(db.String(200), nullable=False)
    customer_phone = db.Column(db.String(50))
    customer_address = db.Column(db.Text)
    total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='pending')
    payment_status = db.Column(db.String(50), default='manual')  # préparé pour Stripe plus tard
    stripe_payment_intent_id = db.Column(db.String(200), nullable=True)
    stripe_session_id = db.Column(db.String(200), nullable=True)
    items = db.Column(db.Text)
    stock_deducted = db.Column(db.Boolean, default=False)
    received_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    service = db.Column(db.String(200))
    date = db.Column(db.String(50))
    time = db.Column(db.String(50))
    message = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    subject = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='new')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class NewsletterSubscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    category = db.Column(db.String(100), default='les_deux')
    status = db.Column(db.String(50), default='active')
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), default='all')
    status = db.Column(db.String(50), default='draft')
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)

# ==================== UTILITAIRES ====================

def slugify(text):
    import re
    text = text.lower()
    replacements = {'à':'a','á':'a','â':'a','ã':'a','ä':'a','è':'e','é':'e','ê':'e','ë':'e',
                     'ì':'i','í':'i','î':'i','ï':'i','ò':'o','ó':'o','ô':'o','õ':'o','ö':'o',
                     'ù':'u','ú':'u','û':'u','ü':'u','ç':'c'}
    for a, b in replacements.items():
        text = text.replace(a, b)
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter pour accéder à cette page', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def customer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'customer_id' not in session:
            flash('Veuillez vous connecter ou créer un compte pour continuer', 'error')
            return redirect(url_for('account_login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

def generate_order_number():
    import random, string
    while True:
        number = 'MG' + ''.join(random.choices(string.digits, k=8))
        if not Order.query.filter_by(order_number=number).first():
            return number

def get_setting(key, default=''):
    setting = Setting.query.filter_by(key=key).first()
    return setting.value if setting else default

def validate_password_strength(password):
    """Retourne (bool, message) — au moins 8 caractères, 1 chiffre, 1 majuscule"""
    import re
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères"
    if not re.search(r'[A-Z]', password):
        return False, "Le mot de passe doit contenir au moins une majuscule"
    if not re.search(r'[0-9]', password):
        return False, "Le mot de passe doit contenir au moins un chiffre"
    return True, ""

# ==================== NEWSLETTER : ENVOI ====================

def generate_unsubscribe_token(email):
    return serializer.dumps(email, salt='newsletter-unsubscribe')

def verify_unsubscribe_token(token, max_age=None):
    try:
        return serializer.loads(token, salt='newsletter-unsubscribe', max_age=max_age)
    except Exception:
        return None

def create_email_template(subject, content, subscriber_email):
    unsubscribe_token = generate_unsubscribe_token(subscriber_email)
    unsubscribe_url = url_for('newsletter_unsubscribe', token=unsubscribe_token, _external=True)
    site_name = get_setting('site_name', 'Magie Groupe')
    phone = get_setting('phone', '')
    email = get_setting('email', '')

    return f"""
    <!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{subject}</title></head>
    <body style="margin:0;padding:0;font-family:Arial,sans-serif;background:#f5f3ee;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 20px;">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.1);">
    <tr><td style="background:#c9a84c;padding:3px;"></td></tr>
    <tr><td style="padding:40px 40px 20px;text-align:center;">
    <h1 style="margin:0;color:#0a0a0a;font-size:32px;">{site_name.upper()}</h1>
    <p style="margin:10px 0 0;color:#888;font-size:14px;letter-spacing:2px;">PRODUCTION AUDIOVISUELLE &amp; E-COMMERCE</p>
    </td></tr>
    <tr><td style="padding:20px 40px 40px;color:#1a1a1a;font-size:16px;line-height:1.6;">{content}</td></tr>
    <tr><td style="padding:0 40px;"><hr style="border:none;border-top:1px solid #e0e0e0;"></td></tr>
    <tr><td style="padding:30px 40px;text-align:center;color:#888;font-size:14px;">
    <p>{site_name}<br>📞 {phone} | ✉️ {email}</p>
    <p style="font-size:12px;color:#999;">
    <a href="{unsubscribe_url}" style="color:#c9a84c;">Se désabonner</a></p>
    </td></tr>
    <tr><td style="background:#c9a84c;padding:3px;"></td></tr>
    </table></td></tr></table></body></html>
    """

def send_newsletter_email(to_email, subject, content):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg['To'] = to_email
        msg.attach(MIMEText(content, 'plain'))
        msg.attach(MIMEText(create_email_template(subject, content, to_email), 'html'))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Erreur envoi email: {e}")
        return False

def create_transactional_email_template(subject, content_html):
    """Template email pour les emails transactionnels (confirmations, reçus) —
    sans lien de désabonnement, contrairement aux emails de newsletter."""
    site_name = get_setting('site_name', 'Magie Groupe')
    phone = get_setting('phone', '')
    email = get_setting('email', '')
    return f"""
    <!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{subject}</title></head>
    <body style="margin:0;padding:0;font-family:Arial,sans-serif;background:#f5f3ee;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 20px;">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.1);">
    <tr><td style="background:#c9a84c;padding:3px;"></td></tr>
    <tr><td style="padding:40px 40px 20px;text-align:center;">
    <h1 style="margin:0;color:#0a0a0a;font-size:32px;">{site_name.upper()}</h1>
    </td></tr>
    <tr><td style="padding:20px 40px 40px;color:#1a1a1a;font-size:15px;line-height:1.6;">{content_html}</td></tr>
    <tr><td style="padding:0 40px;"><hr style="border:none;border-top:1px solid #e0e0e0;"></td></tr>
    <tr><td style="padding:30px 40px;text-align:center;color:#888;font-size:13px;">
    <p>{site_name}<br>{phone} | {email}</p>
    </td></tr>
    <tr><td style="background:#c9a84c;padding:3px;"></td></tr>
    </table></td></tr></table></body></html>
    """

def send_transactional_email(to_email, subject, content_html, content_plain):
    """Envoie un email transactionnel. Retourne True/False selon le succès réel —
    ne jamais annoncer un envoi qui n'a pas vraiment eu lieu."""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg['To'] = to_email
        msg.attach(MIMEText(content_plain, 'plain'))
        msg.attach(MIMEText(create_transactional_email_template(subject, content_html), 'html'))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Erreur envoi email transactionnel: {e}")
        return False

def build_order_items_html(order):
    try:
        items = json.loads(order.items) if order.items else []
    except (json.JSONDecodeError, TypeError):
        items = []
    rows = ""
    for item in items:
        subtotal = item.get('price', 0) * item.get('quantity', 1)
        rows += f"""<tr>
            <td style="padding:8px;border-bottom:1px solid #eee;">{item.get('name','')}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{item.get('quantity',1)}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">{item.get('price',0)} €</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">{subtotal:.2f} €</td>
        </tr>"""
    return f"""<table width="100%" style="border-collapse:collapse;margin:16px 0;font-size:14px;">
        <tr style="background:#f5f3ee;"><th style="padding:8px;text-align:left;">Produit</th><th style="padding:8px;">Qté</th><th style="padding:8px;text-align:right;">Prix</th><th style="padding:8px;text-align:right;">Sous-total</th></tr>
        {rows}
    </table>"""

def send_order_confirmation_email(order):
    """Email envoyé juste après confirmation du paiement."""
    items_html = build_order_items_html(order)
    payment_label = 'Carte bancaire (Stripe)' if order.payment_status == 'paid' else 'En attente'
    content_html = f"""
    <h2 style="margin-top:0;">Confirmation de votre commande</h2>
    <p>Bonjour {order.customer_name},</p>
    <p>Nous avons bien reçu votre paiement. Voici le récapitulatif de votre commande :</p>
    <p><strong>Numéro de commande :</strong> {order.order_number}<br>
    <strong>Date :</strong> {order.created_at.strftime('%d/%m/%Y à %H:%M')}<br>
    <strong>Mode de paiement :</strong> {payment_label}<br>
    <strong>Statut du paiement :</strong> Payé</p>
    {items_html}
    <p style="font-size:18px;font-weight:bold;text-align:right;">Total : {order.total} €</p>
    <p>Merci pour votre confiance !</p>
    """
    content_plain = (
        f"Confirmation de commande {order.order_number}\n"
        f"Total : {order.total} €\n"
        f"Mode de paiement : {payment_label}\n"
        f"Statut : Payé\n"
    )
    return send_transactional_email(order.customer_email, f"Confirmation de votre commande {order.order_number}", content_html, content_plain)

def send_delivery_receipt_email(order):
    """Reçu d'achat envoyé quand l'admin marque la commande comme livrée."""
    items_html = build_order_items_html(order)
    payment_label = 'Carte bancaire (Stripe)' if order.payment_status == 'paid' else order.payment_status
    content_html = f"""
    <h2 style="margin-top:0;">Reçu d'achat — Commande livrée</h2>
    <p>Bonjour {order.customer_name},</p>
    <p>Votre commande a été livrée. Voici votre reçu d'achat :</p>
    <p><strong>Numéro de commande :</strong> {order.order_number}<br>
    <strong>Client :</strong> {order.customer_name} — {order.customer_email}<br>
    <strong>Adresse :</strong> {order.customer_address or '—'}<br>
    <strong>Date de commande :</strong> {order.created_at.strftime('%d/%m/%Y à %H:%M')}<br>
    <strong>Mode de paiement :</strong> {payment_label}<br>
    <strong>Statut :</strong> Livrée</p>
    {items_html}
    <p style="font-size:18px;font-weight:bold;text-align:right;">Total payé : {order.total} €</p>
    <p>Merci pour votre confiance, à bientôt !</p>
    """
    content_plain = f"Reçu d'achat — Commande {order.order_number} livrée. Total : {order.total} €"
    return send_transactional_email(order.customer_email, f"Votre reçu d'achat — Commande {order.order_number}", content_html, content_plain)

def deduct_stock_for_order(order):
    """Diminue le stock des produits d'une commande, une seule fois (idempotent).
    Empêche le stock de descendre sous zéro même en cas d'achats simultanés."""
    if order.stock_deducted:
        return
    try:
        items = json.loads(order.items) if order.items else []
    except (json.JSONDecodeError, TypeError):
        items = []
    for item in items:
        product = Product.query.get(item.get('id'))
        if not product:
            continue
        qty = int(item.get('quantity', 1))
        product.stock = max(0, product.stock - qty)
    order.stock_deducted = True
    db.session.commit()

# ==================== SEO ====================

@app.context_processor
def inject_globals():
    settings = {s.key: s.value for s in Setting.query.all()}
    customer_logged_in = 'customer_id' in session
    customer_unread_count = 0
    if customer_logged_in:
        customer_unread_count = ConversationMessage.query.filter_by(
            customer_id=session['customer_id'], sender='admin', is_read=False
        ).count()
    return dict(
        site_settings=settings,
        site_name=settings.get('site_name', 'Magie Groupe'),
        site_phone=settings.get('phone', ''),
        site_email=settings.get('email', ''),
        site_address=settings.get('address', ''),
        site_whatsapp=settings.get('whatsapp', ''),
        social_instagram=settings.get('instagram', ''),
        social_facebook=settings.get('facebook', ''),
        social_tiktok=settings.get('tiktok', ''),
        customer_logged_in=customer_logged_in,
        customer_name=session.get('customer_name', ''),
        customer_unread_count=customer_unread_count
    )

@app.route('/sitemap.xml')
def sitemap():
    pages = []
    base_url = request.url_root.rstrip('/')
    static_routes = ['index', 'produits', 'portfolio', 'rendez_vous', 'contact']
    for route in static_routes:
        pages.append(f"<url><loc>{base_url}{url_for(route)}</loc><changefreq>weekly</changefreq></url>")
    for p in Product.query.all():
        pages.append(f"<url><loc>{base_url}{url_for('product_detail', slug=p.slug)}</loc><changefreq>weekly</changefreq></url>")
    for pr in Project.query.all():
        pages.append(f"<url><loc>{base_url}{url_for('project_detail', slug=pr.slug)}</loc><changefreq>monthly</changefreq></url>")
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{"".join(pages)}</urlset>'
    return Response(xml, mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    base_url = request.url_root.rstrip('/')
    content = f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {base_url}/sitemap.xml"
    return Response(content, mimetype='text/plain')

# ==================== ROUTES PUBLIQUES ====================

@app.route('/')
def index():
    featured_products = Product.query.filter_by(featured=True).limit(3).all()
    featured_projects = Project.query.filter_by(featured=True).limit(3).all()
    return render_template('public/index.html',
                            featured_products=featured_products,
                            featured_projects=featured_projects)

@app.route('/produits')
def produits():
    category = request.args.get('category')
    q = Product.query
    if category:
        q = q.filter_by(category=category)
    return render_template('public/produits.html', products=q.all())

@app.route('/produits/<slug>')
def product_detail(slug):
    product = Product.query.filter_by(slug=slug).first_or_404()
    return render_template('public/product_detail.html', product=product)

@app.route('/portfolio')
def portfolio():
    category = request.args.get('category')
    q = Project.query
    if category:
        q = q.filter_by(category=category)
    return render_template('public/portfolio.html', projects=q.all())

@app.route('/portfolio/<slug>')
def project_detail(slug):
    project = Project.query.filter_by(slug=slug).first_or_404()
    return render_template('public/project_detail.html', project=project)

@app.route('/rendez-vous', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def rendez_vous():
    if request.method == 'POST':
        appointment = Appointment(
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            service=request.form.get('service'),
            date=request.form.get('date'),
            time=request.form.get('time'),
            message=request.form.get('message')
        )
        db.session.add(appointment)
        db.session.commit()
        flash('Votre demande de rendez-vous a été envoyée avec succès', 'success')
        return redirect(url_for('rendez_vous'))
    return render_template('public/rendez_vous.html')

@app.route('/contact', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def contact():
    if request.method == 'POST':
        contact = Contact(
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            subject=request.form.get('subject'),
            message=request.form.get('message')
        )
        db.session.add(contact)
        db.session.commit()
        flash('Votre message a été envoyé avec succès. Nous vous répondrons rapidement.', 'success')
        return redirect(url_for('contact'))
    return render_template('public/contact.html')

@app.route('/panier')
def panier():
    return render_template('public/panier.html')

# ==================== COMPTE CLIENT ====================

@app.route('/compte/inscription', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def account_register():
    if 'customer_id' in session:
        return redirect(url_for('account_dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not name or not email or not password:
            flash('Veuillez remplir tous les champs obligatoires', 'error')
            return render_template('public/account_register.html')

        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'error')
            return render_template('public/account_register.html')

        valid, msg = validate_password_strength(password)
        if not valid:
            flash(msg, 'error')
            return render_template('public/account_register.html')

        if Customer.query.filter_by(email=email).first():
            flash('Un compte existe déjà avec cet email', 'error')
            return render_template('public/account_register.html')

        customer = Customer(
            name=name,
            email=email,
            phone=phone,
            address=address,
            password_hash=generate_password_hash(password)
        )
        db.session.add(customer)
        db.session.commit()

        session.permanent = True
        session['customer_id'] = customer.id
        session['customer_name'] = customer.name
        flash('Compte créé avec succès, bienvenue !', 'success')

        next_url = request.args.get('next') or request.form.get('next')
        return redirect(next_url or url_for('account_dashboard'))

    return render_template('public/account_register.html')

@app.route('/compte/connexion', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def account_login():
    if 'customer_id' in session:
        return redirect(url_for('account_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        customer = Customer.query.filter_by(email=email).first()
        if customer and check_password_hash(customer.password_hash, password):
            session.permanent = True
            session['customer_id'] = customer.id
            session['customer_name'] = customer.name
            flash(f'Bon retour, {customer.name} !', 'success')
            next_url = request.args.get('next') or request.form.get('next')
            return redirect(next_url or url_for('account_dashboard'))
        else:
            flash('Email ou mot de passe incorrect', 'error')

    return render_template('public/account_login.html')

@app.route('/compte/deconnexion')
def account_logout():
    session.pop('customer_id', None)
    session.pop('customer_name', None)
    flash('Vous avez été déconnecté', 'info')
    return redirect(url_for('index'))

@app.route('/compte')
@customer_login_required
def account_dashboard():
    customer = Customer.query.get(session['customer_id'])
    orders = Order.query.filter_by(customer_id=customer.id).order_by(Order.created_at.desc()).all()
    unread_count = ConversationMessage.query.filter_by(
        customer_id=customer.id, sender='admin', is_read=False
    ).count()
    return render_template('public/account_dashboard.html', customer=customer, orders=orders, unread_count=unread_count)

@app.route('/compte/commande/<order_number>')
@customer_login_required
def account_order_detail(order_number):
    customer = Customer.query.get(session['customer_id'])
    order = Order.query.filter_by(order_number=order_number, customer_id=customer.id).first_or_404()
    try:
        items = json.loads(order.items) if order.items else []
    except (json.JSONDecodeError, TypeError):
        items = []
    return render_template('public/account_order_detail.html', order=order, items=items)

@app.route('/compte/commande/<order_number>/recu', methods=['POST'])
@customer_login_required
def account_confirm_reception(order_number):
    customer = Customer.query.get(session['customer_id'])
    order = Order.query.filter_by(order_number=order_number, customer_id=customer.id).first_or_404()
    order.received_at = datetime.utcnow()
    if order.status == 'shipped':
        order.status = 'delivered'
    db.session.commit()
    flash('Merci d\'avoir confirmé la réception de votre commande !', 'success')
    return redirect(url_for('account_order_detail', order_number=order_number))

@app.route('/compte/messages', methods=['GET', 'POST'])
@customer_login_required
def account_messages():
    customer = Customer.query.get(session['customer_id'])

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if content:
            db.session.add(ConversationMessage(customer_id=customer.id, sender='customer', content=content))
            db.session.commit()
        return redirect(url_for('account_messages'))

    # Marquer les messages admin comme lus dès que le client consulte la page
    ConversationMessage.query.filter_by(customer_id=customer.id, sender='admin', is_read=False).update({'is_read': True})
    db.session.commit()

    messages = ConversationMessage.query.filter_by(customer_id=customer.id).order_by(ConversationMessage.created_at.asc()).all()
    return render_template('public/account_messages.html', customer=customer, messages=messages)


@app.route('/checkout', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
@customer_login_required
def checkout():
    if request.method == 'POST':
        # Validation serveur des articles, prix ET stock — ne JAMAIS faire confiance
        # aux données envoyées par le navigateur quand de l'argent réel est en jeu.
        try:
            raw_items = json.loads(request.form.get('items', '[]'))
        except (json.JSONDecodeError, TypeError):
            raw_items = []

        validated_items = []
        total = 0.0
        stock_errors = []
        for raw in raw_items:
            product = Product.query.get(raw.get('id'))
            if not product:
                continue
            qty = max(1, int(raw.get('quantity', 1)))
            if qty > product.stock:
                stock_errors.append(f"{product.name} : seulement {product.stock} en stock (demandé : {qty})")
                continue
            validated_items.append({
                'id': product.id,
                'name': product.name,
                'price': product.price,
                'image': product.image,
                'quantity': qty
            })
            total += product.price * qty

        if stock_errors:
            flash('Stock insuffisant pour : ' + ' ; '.join(stock_errors), 'error')
            return redirect(url_for('panier'))

        if not validated_items:
            flash('Votre panier est vide ou invalide', 'error')
            return redirect(url_for('panier'))

        order = Order(
            order_number=generate_order_number(),
            customer_id=session['customer_id'],
            customer_name=request.form.get('name'),
            customer_email=request.form.get('email'),
            customer_phone=request.form.get('phone'),
            customer_address=request.form.get('address'),
            total=round(total, 2),
            items=json.dumps(validated_items),
            status='pending',
            payment_status='pending'
        )
        db.session.add(order)
        db.session.commit()

        # ⚠️ VÉRIFICATION STRIPE - CRITIQUE
        if not stripe.api_key:
            print(f"❌ STRIPE: clé API absente — mode dégradé pour commande {order.order_number}")
            flash('⚠️ Paiement Stripe non configuré. Votre commande a été enregistrée en mode manuel. L\'équipe vous contactera.', 'warning')
            return redirect(url_for('order_success', order_number=order.order_number))

        line_items = [{
            'price_data': {
                'currency': 'eur',
                'product_data': {'name': item['name']},
                'unit_amount': int(round(item['price'] * 100)),
            },
            'quantity': item['quantity'],
        } for item in validated_items]

        try:
            checkout_session = stripe.checkout.Session.create(
                line_items=line_items,
                mode='payment',
                success_url=url_for('order_success', order_number=order.order_number, _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('checkout', _external=True),
                customer_email=order.customer_email,
                client_reference_id=order.order_number,
            )
            print(f"✅ STRIPE: session créée {checkout_session.id} pour commande {order.order_number}")
        except Exception as e:
            print(f"❌ STRIPE: erreur création session — {repr(e)}")
            flash(f"Erreur paiement Stripe : {e}", 'error')
            order.status = 'cancelled'
            db.session.commit()
            return redirect(url_for('checkout'))

        order.stripe_session_id = checkout_session.id
        db.session.commit()

        return redirect(checkout_session.url, code=303)

    return render_template('public/checkout.html', customer=Customer.query.get(session['customer_id']))

@app.route('/success/<order_number>')
def order_success(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()

    session_id = request.args.get('session_id')
    if session_id and order.payment_status != 'paid' and stripe.api_key:
        try:
            checkout_session = stripe.checkout.Session.retrieve(session_id)
            print(f"✅ STRIPE: vérification session {session_id} -> payment_status = {checkout_session.payment_status}")
            if checkout_session.payment_status == 'paid':
                order.payment_status = 'paid'
                order.status = 'confirmed'
                order.stripe_payment_intent_id = checkout_session.payment_intent
                db.session.commit()
                deduct_stock_for_order(order)
                print(f"✅ Commande {order_number} confirmée via session Stripe")
        except Exception as e:
            print(f"❌ STRIPE: erreur vérification session — {repr(e)}")

    email_sent = False
    if order.payment_status == 'paid':
        email_sent = send_order_confirmation_email(order)
        if not email_sent:
            print(f"⚠️  Email de confirmation NOT SENT pour commande {order_number} (SMTP non configuré ?)")

    return render_template('public/success.html', order=order, email_sent=email_sent)

@app.route('/stripe/webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    """Reçoit les confirmations de paiement de Stripe.
    Source de vérité fiable même si le client ferme son navigateur
    avant la redirection vers la page de succès.
    
    ⚠️ CRITIQUE : STRIPE_WEBHOOK_SECRET DOIT être défini en production !
    """
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    if not STRIPE_WEBHOOK_SECRET:
        print("❌ STRIPE WEBHOOK: STRIPE_WEBHOOK_SECRET absent — webhook IGNORÉ")
        return {'error': 'Webhook secret not configured'}, 403

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError as e:
        print(f"❌ STRIPE WEBHOOK: payload invalide — {repr(e)}")
        return '', 400
    except stripe.error.SignatureVerificationError as e:
        print(f"❌ STRIPE WEBHOOK: signature invalide — {repr(e)}")
        return '', 400

    print(f"✅ STRIPE WEBHOOK: événement reçu — {event['type']}")

    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        order_number = session_obj.get('client_reference_id')
        order = Order.query.filter_by(order_number=order_number).first()
        if order and order.payment_status != 'paid':
            order.payment_status = 'paid'
            order.status = 'confirmed'
            order.stripe_payment_intent_id = session_obj.get('payment_intent')
            db.session.commit()
            deduct_stock_for_order(order)
            email_sent = send_order_confirmation_email(order)
            if email_sent:
                print(f"✅ Commande {order_number} confirmée + email envoyé via webhook")
            else:
                print(f"⚠️  Commande {order_number} confirmée mais email NOT SENT")
        else:
            print(f"⚠️  Webhook reçu mais commande {order_number} introuvable ou déjà payée")

    return '', 200
    
@app.route('/newsletter/subscribe', methods=['POST'])
@limiter.limit("5 per hour")
def newsletter_subscribe():
    # Le footer envoie du JSON via fetch() ; on garde un fallback formulaire classique
    if request.is_json:
        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip().lower()
        category = data.get('category', 'les_deux')
    else:
        email = request.form.get('email', '').strip().lower()
        category = request.form.get('category', 'les_deux')

    if not email or '@' not in email:
        message, success = 'Adresse email invalide', False
    else:
        existing = NewsletterSubscriber.query.filter_by(email=email).first()
        if existing:
            if existing.status == 'unsubscribed':
                existing.status = 'active'
                db.session.commit()
                message, success = 'Vous êtes de nouveau abonné', True
            else:
                message, success = 'Cet email est déjà abonné', True
        else:
            db.session.add(NewsletterSubscriber(email=email, category=category))
            db.session.commit()
            message, success = 'Merci de vous être abonné à notre newsletter', True

    if request.is_json:
        return {'success': success, 'message': message}
    flash(message, 'success' if success else 'error')
    return redirect(request.referrer or url_for('index'))

@app.route('/newsletter/unsubscribe/<token>')
def newsletter_unsubscribe(token):
    email = verify_unsubscribe_token(token, max_age=60*60*24*365)
    if not email:
        flash('Lien de désabonnement invalide ou expiré', 'error')
        return redirect(url_for('index'))
    subscriber = NewsletterSubscriber.query.filter_by(email=email).first()
    if subscriber:
        subscriber.status = 'unsubscribed'
        db.session.commit()
        flash('Vous avez été désabonné de notre newsletter', 'success')
    return render_template('public/unsubscribe_success.html')

# ==================== ROUTES ADMIN ====================

@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.locked_until and user.locked_until > datetime.utcnow():
            flash('Compte temporairement bloqué suite à plusieurs échecs. Réessayez dans quelques minutes.', 'error')
            return render_template('admin/login.html')

        if user and check_password_hash(user.password_hash, password):
            user.failed_attempts = 0
            user.locked_until = None
            db.session.commit()
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Connexion réussie', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            if user:
                user.failed_attempts = (user.failed_attempts or 0) + 1
                if user.failed_attempts >= 5:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=15)
                db.session.commit()
            flash('Identifiants incorrects', 'error')

    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('Vous avez été déconnecté', 'info')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    stats = {
        'products': Product.query.count(),
        'projects': Project.query.count(),
        'orders': Order.query.count(),
        'pending_orders': Order.query.filter_by(status='pending').count(),
        'appointments': Appointment.query.count(),
        'pending_appointments': Appointment.query.filter_by(status='pending').count(),
        'contacts': Contact.query.filter_by(status='new').count(),
        'subscribers': NewsletterSubscriber.query.filter_by(status='active').count(),
        'customers': Customer.query.count(),
        'unread_customer_messages': ConversationMessage.query.filter_by(sender='customer', is_read=False).count()
    }
    return render_template('admin/dashboard.html', stats=stats)

@app.route('/admin/change-password', methods=['GET', 'POST'])
@login_required
def admin_change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        user = User.query.get(session['user_id'])
        if not check_password_hash(user.password_hash, current_password):
            flash('Mot de passe actuel incorrect', 'error')
            return redirect(url_for('admin_change_password'))

        if new_password != confirm_password:
            flash('Les nouveaux mots de passe ne correspondent pas', 'error')
            return redirect(url_for('admin_change_password'))

        valid, msg = validate_password_strength(new_password)
        if not valid:
            flash(msg, 'error')
            return redirect(url_for('admin_change_password'))

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('Mot de passe modifié avec succès', 'success')
        return redirect(url_for('admin_settings'))

    return render_template('admin/change_password.html')

# ---------- Products ----------

@app.route('/admin/products')
@login_required
def admin_products():
    return render_template('admin/products.html', products=Product.query.all())

@app.route('/admin/products/stock-critique')
@login_required
def admin_stock_critique():
    try:
        seuil = int(get_setting('stock_seuil_critique', '5'))
    except (ValueError, TypeError):
        seuil = 5
    produits_critiques = Product.query.filter(Product.stock <= seuil).order_by(Product.stock.asc()).all()
    return render_template('admin/stock_critique.html', produits=produits_critiques, seuil=seuil)

@app.route('/admin/products/stock-critique/seuil', methods=['POST'])
@login_required
def admin_update_seuil_critique():
    valeur = request.form.get('seuil', '5')
    setting = Setting.query.filter_by(key='stock_seuil_critique').first()
    if setting:
        setting.value = valeur
    else:
        db.session.add(Setting(key='stock_seuil_critique', value=valeur))
    db.session.commit()
    flash('Seuil de stock critique mis à jour', 'success')
    return redirect(url_for('admin_stock_critique'))

@app.route('/admin/products/new', methods=['GET', 'POST'])
@login_required
def admin_new_product():
    if request.method == 'POST':
        name = request.form.get('name')
        image_url = upload_image(request.files.get('image'))
        product = Product(
            name=name,
            slug=slugify(name),
            description=request.form.get('description'),
            price=float(request.form.get('price')),
            category=request.form.get('category'),
            location=request.form.get('location'),
            stock=int(request.form.get('stock', 0)),
            image=image_url,
            featured=bool(request.form.get('featured'))
        )
        db.session.add(product)
        db.session.commit()
        flash('Produit créé avec succès', 'success')
        return redirect(url_for('admin_products'))
    return render_template('admin/product_form.html')

@app.route('/admin/products/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_edit_product(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        product.name = request.form.get('name')
        product.slug = slugify(product.name)
        product.description = request.form.get('description')
        product.price = float(request.form.get('price'))
        product.category = request.form.get('category')
        product.location = request.form.get('location')
        product.stock = int(request.form.get('stock', 0))
        product.featured = bool(request.form.get('featured'))

        new_image = upload_image(request.files.get('image'))
        if new_image:
            delete_image(product.image)
            product.image = new_image

        db.session.commit()
        flash('Produit modifié avec succès', 'success')
        return redirect(url_for('admin_products'))
    return render_template('admin/product_form.html', product=product)

@app.route('/admin/products/delete/<int:id>', methods=['POST'])
@login_required
def admin_delete_product(id):
    product = Product.query.get_or_404(id)
    delete_image(product.image)
    db.session.delete(product)
    db.session.commit()
    flash('Produit supprimé avec succès', 'success')
    return redirect(url_for('admin_products'))

# ---------- Projects ----------

@app.route('/admin/projects')
@login_required
def admin_projects():
    return render_template('admin/projects.html', projects=Project.query.all())

@app.route('/admin/projects/new', methods=['GET', 'POST'])
@login_required
def admin_new_project():
    if request.method == 'POST':
        title = request.form.get('title')
        image_url = upload_image(request.files.get('image'))
        project = Project(
            title=title,
            slug=slugify(title),
            description=request.form.get('description'),
            category=request.form.get('category'),
            client=request.form.get('client'),
            date=request.form.get('date'),
            image=image_url,
            video_url=request.form.get('video_url'),
            featured=bool(request.form.get('featured'))
        )
        db.session.add(project)
        db.session.commit()
        flash('Projet créé avec succès', 'success')
        return redirect(url_for('admin_projects'))
    return render_template('admin/project_form.html')

@app.route('/admin/projects/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_edit_project(id):
    project = Project.query.get_or_404(id)
    if request.method == 'POST':
        project.title = request.form.get('title')
        project.slug = slugify(project.title)
        project.description = request.form.get('description')
        project.category = request.form.get('category')
        project.client = request.form.get('client')
        project.date = request.form.get('date')
        project.video_url = request.form.get('video_url')
        project.featured = bool(request.form.get('featured'))

        new_image = upload_image(request.files.get('image'))
        if new_image:
            delete_image(project.image)
            project.image = new_image

        db.session.commit()
        flash('Projet modifié avec succès', 'success')
        return redirect(url_for('admin_projects'))
    return render_template('admin/project_form.html', project=project)

@app.route('/admin/projects/delete/<int:id>', methods=['POST'])
@login_required
def admin_delete_project(id):
    project = Project.query.get_or_404(id)
    delete_image(project.image)
    db.session.delete(project)
    db.session.commit()
    flash('Projet supprimé avec succès', 'success')
    return redirect(url_for('admin_projects'))

# ---------- Orders ----------

@app.route('/admin/orders')
@login_required
def admin_orders():
    return render_template('admin/orders.html', orders=Order.query.order_by(Order.created_at.desc()).all())

@app.route('/admin/orders/<int:id>')
@login_required
def admin_order_detail(id):
    order = Order.query.get_or_404(id)
    try:
        items = json.loads(order.items) if order.items else []
    except (json.JSONDecodeError, TypeError):
        items = []
    return render_template('admin/order_detail.html', order=order, items=items)

@app.route('/admin/orders/<int:id>/status', methods=['POST'])
@login_required
def admin_update_order_status(id):
    order = Order.query.get_or_404(id)
    new_status = request.form.get('status')
    was_delivered_before = order.status == 'delivered'
    order.status = new_status
    db.session.commit()

    if new_status == 'delivered' and not was_delivered_before:
        sent = send_delivery_receipt_email(order)
        if sent:
            flash('Statut mis à jour, reçu envoyé par email au client', 'success')
        else:
            flash('Statut mis à jour, mais l\'envoi du reçu par email a échoué (SMTP non configuré ?)', 'info')
    else:
        flash('Statut de commande mis à jour', 'success')

    return redirect(url_for('admin_order_detail', id=id))

@app.route('/admin/orders/delete/<int:id>', methods=['POST'])
@login_required
def admin_delete_order(id):
    db.session.delete(Order.query.get_or_404(id))
    db.session.commit()
    flash('Commande supprimée avec succès', 'success')
    return redirect(url_for('admin_orders'))

# ---------- Appointments ----------

@app.route('/admin/appointments')
@login_required
def admin_appointments():
    return render_template('admin/appointments.html', appointments=Appointment.query.order_by(Appointment.created_at.desc()).all())

@app.route('/admin/appointments/<int:id>')
@login_required
def admin_appointment_detail(id):
    return render_template('admin/appointment_detail.html', appointment=Appointment.query.get_or_404(id))

@app.route('/admin/appointments/<int:id>/status', methods=['POST'])
@login_required
def admin_update_appointment_status(id):
    appointment = Appointment.query.get_or_404(id)
    appointment.status = request.form.get('status')
    db.session.commit()
    flash('Statut de rendez-vous mis à jour', 'success')
    return redirect(url_for('admin_appointment_detail', id=id))

@app.route('/admin/appointments/delete/<int:id>', methods=['POST'])
@login_required
def admin_delete_appointment(id):
    db.session.delete(Appointment.query.get_or_404(id))
    db.session.commit()
    flash('Rendez-vous supprimé avec succès', 'success')
    return redirect(url_for('admin_appointments'))

# ---------- Contacts ----------

@app.route('/admin/contacts')
@login_required
def admin_contacts():
    return render_template('admin/contacts.html', contacts=Contact.query.order_by(Contact.created_at.desc()).all())

@app.route('/admin/contacts/<int:id>')
@login_required
def admin_contact_detail(id):
    contact = Contact.query.get_or_404(id)
    if contact.status == 'new':
        contact.status = 'read'
        db.session.commit()
    return render_template('admin/contact_detail.html', contact=contact)

@app.route('/admin/contacts/delete/<int:id>', methods=['POST'])
@login_required
def admin_delete_contact(id):
    db.session.delete(Contact.query.get_or_404(id))
    db.session.commit()
    flash('Message supprimé avec succès', 'success')
    return redirect(url_for('admin_contacts'))

# ---------- Newsletter ----------

@app.route('/admin/customers')
@login_required
def admin_customers():
    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    unread_map = {}
    for c in customers:
        unread_map[c.id] = ConversationMessage.query.filter_by(customer_id=c.id, sender='customer', is_read=False).count()
    return render_template('admin/customers.html', customers=customers, unread_map=unread_map)

@app.route('/admin/customers/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_customer_detail(id):
    customer = Customer.query.get_or_404(id)

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if content:
            db.session.add(ConversationMessage(customer_id=customer.id, sender='admin', content=content))
            db.session.commit()
        return redirect(url_for('admin_customer_detail', id=id))

    ConversationMessage.query.filter_by(customer_id=customer.id, sender='customer', is_read=False).update({'is_read': True})
    db.session.commit()

    messages = ConversationMessage.query.filter_by(customer_id=customer.id).order_by(ConversationMessage.created_at.asc()).all()
    orders = Order.query.filter_by(customer_id=customer.id).order_by(Order.created_at.desc()).all()
    return render_template('admin/customer_detail.html', customer=customer, messages=messages, orders=orders)

@app.route('/admin/newsletter')
@login_required
def admin_newsletter():
    return render_template('admin/newsletter.html', subscribers=NewsletterSubscriber.query.order_by(NewsletterSubscriber.subscribed_at.desc()).all())

@app.route('/admin/newsletter/delete/<int:id>', methods=['POST'])
@login_required
def admin_delete_subscriber(id):
    db.session.delete(NewsletterSubscriber.query.get_or_404(id))
    db.session.commit()
    flash('Abonné supprimé avec succès', 'success')
    return redirect(url_for('admin_newsletter'))

# ---------- Campaigns ----------

@app.route('/admin/campaigns')
@login_required
def admin_campaigns():
    return render_template('admin/campaigns.html', campaigns=Campaign.query.order_by(Campaign.created_at.desc()).all())

@app.route('/admin/campaigns/new', methods=['GET', 'POST'])
@login_required
def admin_new_campaign():
    if request.method == 'POST':
        campaign = Campaign(
            title=request.form.get('title'),
            subject=request.form.get('subject'),
            content=request.form.get('content'),
            category=request.form.get('category')
        )
        db.session.add(campaign)
        db.session.commit()
        flash('Campagne créée avec succès', 'success')
        return redirect(url_for('admin_campaigns'))
    return render_template('admin/campaign_form.html')

@app.route('/admin/campaigns/send/<int:id>', methods=['POST'])
@login_required
def admin_send_campaign(id):
    campaign = Campaign.query.get_or_404(id)
    if campaign.category == 'all':
        subscribers = NewsletterSubscriber.query.filter_by(status='active').all()
    else:
        subscribers = NewsletterSubscriber.query.filter(
            NewsletterSubscriber.status == 'active',
            (NewsletterSubscriber.category == campaign.category) |
            (NewsletterSubscriber.category == 'les_deux')
        ).all()

    sent_count = sum(1 for s in subscribers if send_newsletter_email(s.email, campaign.subject, campaign.content))

    campaign.status = 'sent'
    campaign.sent_at = datetime.utcnow()
    db.session.commit()
    flash(f'Campagne envoyée à {sent_count} abonnés', 'success')
    return redirect(url_for('admin_campaigns'))

@app.route('/admin/campaigns/delete/<int:id>', methods=['POST'])
@login_required
def admin_delete_campaign(id):
    db.session.delete(Campaign.query.get_or_404(id))
    db.session.commit()
    flash('Campagne supprimée avec succès', 'success')
    return redirect(url_for('admin_campaigns'))

# ---------- Payments (Stripe) ----------

@app.route('/admin/payments', methods=['GET'])
@login_required
def admin_payments():
    """Affiche l'historique des paiements Stripe."""
    if not stripe.api_key:
        flash('Stripe non configuré', 'error')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Récupère les 50 derniers paiements
        charges = stripe.Charge.list(limit=50)
        
        # Format pour affichage
        payments = []
        for charge in charges.data:
            payments.append({
                'id': charge.id,
                'amount': charge.amount / 100,  # Convertir de cents en euros
                'currency': charge.currency.upper(),
                'status': charge.status,
                'customer': charge.customer or 'N/A',
                'created': charge.created,
                'description': charge.description or 'N/A',
                'paid': charge.paid,
                'refunded': charge.refunded
            })
        
        return render_template('admin/payments.html', payments=payments)
    except Exception as e:
        print(f"❌ Erreur récupération charges Stripe : {e}")
        flash(f'Erreur accès Stripe : {e}', 'error')
        return redirect(url_for('admin_dashboard'))
        
# ---------- Settings ----------

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if request.method == 'POST':
        keys = ['site_name', 'phone', 'email', 'address', 'whatsapp',
                'instagram', 'facebook', 'tiktok', 'meta_description']
        for key in keys:
            value = request.form.get(key)
            setting = Setting.query.filter_by(key=key).first()
            if setting:
                setting.value = value
            else:
                db.session.add(Setting(key=key, value=value))
        db.session.commit()
        flash('Paramètres mis à jour avec succès', 'success')
        return redirect(url_for('admin_settings'))

    settings = {s.key: s.value for s in Setting.query.all()}
    return render_template('admin/settings.html', settings=settings)

# ==================== INITIALISATION BASE DE DONNÉES (TEMPORAIRE) ====================
# À VISITER UNE SEULE FOIS depuis le navigateur, puis à SUPPRIMER de app.py.
# URL volontairement longue/aléatoire pour éviter tout accès non désiré.

@app.route('/setup-database-mg2026-x7k9p3')
def setup_database_once():
    db.create_all()

    # db.create_all() ne modifie JAMAIS les tables déjà existantes — il ne fait
    # que créer les nouvelles. Ces colonnes ont été ajoutées aux modèles après
    # la création initiale des tables 'order' et 'user' : on les ajoute ici
    # manuellement si elles manquent encore. Sûr à rejouer plusieurs fois.
    from sqlalchemy import text
    migrations = [
        'ALTER TABLE "order" ADD COLUMN IF NOT EXISTS customer_id INTEGER',
        'ALTER TABLE "order" ADD COLUMN IF NOT EXISTS stripe_payment_intent_id VARCHAR(200)',
        'ALTER TABLE "order" ADD COLUMN IF NOT EXISTS stripe_session_id VARCHAR(200)',
        'ALTER TABLE "order" ADD COLUMN IF NOT EXISTS stock_deducted BOOLEAN DEFAULT FALSE',
        'ALTER TABLE "order" ADD COLUMN IF NOT EXISTS received_at TIMESTAMP',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS failed_attempts INTEGER DEFAULT 0',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP',
    ]
    migration_log = []
    for stmt in migrations:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
            migration_log.append(f"OK: {stmt}")
        except Exception as e:
            db.session.rollback()
            migration_log.append(f"SKIP ({e.__class__.__name__}): {stmt}")

    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password_hash=generate_password_hash('MagieGroupe2025!')
        )
        db.session.add(admin)

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
    return (
        "Base de donnees initialisee et migree avec succes.<br><br>" +
        "<br>".join(migration_log) +
        "<br><br>Compte admin : admin / MagieGroupe2025! " +
        "IMPORTANT : supprimez maintenant cette route de app.py et changez le mot de passe admin.",
        200
    )

# ==================== POINT D'ENTRÉE VERCEL ====================
# Vercel importe directement la variable `app` de ce fichier — rien de plus à faire.

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
