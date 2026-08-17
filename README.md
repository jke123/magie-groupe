# 🎬 Magie Groupe — Site E-Commerce & Portfolio Audiovisuel

Site prêt pour déploiement Vercel + Neon Postgres + Cloudinary.

## 📖 À lire en premier

**`CHECKLIST_CE_SOIR.md`** — guide complet étape par étape, de la création
des comptes (Neon, Cloudinary) jusqu'au déploiement Vercel et à Google Search Console.

## 📂 Structure du projet

```
app.py                          → Backend Flask complet
vercel.json                     → Config déploiement Vercel
requirements.txt                → Dépendances Python
init_db.py                      → Script d'initialisation DB (à lancer 1 fois en local)
.env.example                    → Variables d'environnement à configurer

templates/
  public/                       → Pages visibles par les visiteurs
    base.html, index.html, produits.html, contact.html,
    rendez_vous.html, unsubscribe_success.html
  admin/                        → Panel administrateur
    products.html, projects.html, orders.html, appointments.html,
    contacts.html, newsletter.html, campaigns.html, settings.html,
    change_password.html

static/
  css/
    style.css                   → Design principal (noir/or)
    enhancements.css            → Animations, transitions, effets premium
    admin-buttons.css           → Styles boutons suppression admin
  js/
    animations.js               → Reveal au scroll, loader, retour en haut
```

## ⚠️ Fichiers manquants à recréer/compléter avant déploiement

Certains templates référencés dans app.py ne sont pas encore dans ce ZIP
(ils dépendent de votre contenu spécifique ou ont été décrits mais pas
générés en fichier complet dans nos échanges) :

- `templates/public/portfolio.html`
- `templates/public/product_detail.html`
- `templates/public/project_detail.html`
- `templates/public/panier.html`
- `templates/public/checkout.html`
- `templates/public/success.html`
- `templates/admin/base.html` (layout admin)
- `templates/admin/login.html`
- `templates/admin/dashboard.html`
- `templates/admin/product_form.html`
- `templates/admin/project_form.html`
- `templates/admin/order_detail.html`
- `templates/admin/appointment_detail.html`
- `templates/admin/contact_detail.html`
- `templates/admin/campaign_form.html`

👉 Si vous les avez déjà sur votre dépôt GitHub actuel, gardez-les tels
quels — n'appliquez que les points de la CHECKLIST (CSRF token, URLs
Cloudinary pour les images, liens CSS/JS ajoutés dans base.html).
Si vous ne les avez plus, dites-le et je les régénère.

## 🔧 Avant de déployer

1. Configurer `.env` à partir de `.env.example`
2. `pip install -r requirements.txt`
3. `python init_db.py`
4. Suivre `CHECKLIST_CE_SOIR.md` à partir de l'étape 4

## 🔒 Sécurité incluse

- Mots de passe hashés (pbkdf2:sha256)
- Blocage compte après 5 échecs de connexion
- Protection CSRF (à finaliser : ajouter le token dans chaque formulaire)
- Cookies de session sécurisés
- Rate limiting sur connexion et formulaires publics
- En-têtes de sécurité HTTP

## 💳 Paiement

Champ `payment_status` déjà prévu dans les commandes pour une intégration
Stripe future (compatible France).
