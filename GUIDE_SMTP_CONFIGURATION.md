# ============================================
# GUIDE DE CONFIGURATION SMTP POUR NEWSLETTER
# ============================================

## OPTION 1 : Gmail (Recommandé pour débuter)

### 1. Créer un "App Password" Gmail

1. Aller sur https://myaccount.google.com/security
2. Activer la validation en 2 étapes si pas déjà fait
3. Rechercher "App passwords" (Mots de passe des applications)
4. Sélectionner "Mail" et "Autre (nom personnalisé)"
5. Nommer : "Magie Groupe Newsletter"
6. Copier le mot de passe généré (16 caractères)

### 2. Configuration dans app.py

```python
# Configuration SMTP Gmail
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USERNAME = 'votre-email@gmail.com'  # Votre email Gmail
SMTP_PASSWORD = 'xxxx xxxx xxxx xxxx'    # Le App Password (16 caractères)
SMTP_FROM_EMAIL = 'votre-email@gmail.com'
SMTP_FROM_NAME = 'Magie Groupe'
```

### 3. Limites Gmail Gratuit
- 500 emails / jour
- 100 destinataires par email
- Suffisant pour démarrer


## OPTION 2 : Outlook/Office365

### Configuration

```python
SMTP_SERVER = 'smtp.office365.com'
SMTP_PORT = 587
SMTP_USERNAME = 'votre-email@outlook.com'
SMTP_PASSWORD = 'votre-mot-de-passe'
SMTP_FROM_EMAIL = 'votre-email@outlook.com'
SMTP_FROM_NAME = 'Magie Groupe'
```

### Limites
- 300 emails / jour
- 100 destinataires par email


## OPTION 3 : Sendinblue (Gratuit jusqu'à 300/jour)

### 1. Créer compte sur https://www.sendinblue.com

### 2. Récupérer clé API
- SMTP & API > SMTP
- Copier login et mot de passe SMTP

### 3. Configuration

```python
SMTP_SERVER = 'smtp-relay.sendinblue.com'
SMTP_PORT = 587
SMTP_USERNAME = 'votre-login-sendinblue'
SMTP_PASSWORD = 'votre-mot-de-passe-sendinblue'
SMTP_FROM_EMAIL = 'contact@magiegroupe.com'  # Votre email vérifié
SMTP_FROM_NAME = 'Magie Groupe'
```

### Avantages Sendinblue
- 300 emails/jour GRATUIT
- Statistiques d'ouverture/clics
- Templates professionnels
- Pas de spam
- Support


## OPTION 4 : Mailgun (Pour volumes importants)

### 1. Créer compte sur https://www.mailgun.com
- Plan gratuit : 5000 emails/mois pendant 3 mois

### 2. Configuration

```python
SMTP_SERVER = 'smtp.mailgun.org'
SMTP_PORT = 587
SMTP_USERNAME = 'postmaster@votredomaine.mailgun.org'
SMTP_PASSWORD = 'votre-clé-smtp'
SMTP_FROM_EMAIL = 'contact@magiegroupe.com'
SMTP_FROM_NAME = 'Magie Groupe'
```


## INSTALLATION DES DÉPENDANCES

Ajouter dans requirements.txt :
```
itsdangerous==2.1.2
```

Installer :
```bash
pip install itsdangerous
```


## TESTS AVANT PRODUCTION

### 1. Test simple

```python
# Dans Python console ou script test
from app import send_newsletter_email

# Envoyer à votre propre email
result = send_newsletter_email(
    'votre-email@gmail.com',
    'Test Newsletter',
    '<h2>Bonjour !</h2><p>Ceci est un test.</p>'
)

print("Envoyé !" if result else "Erreur !")
```

### 2. Vérifier réception
- Vérifier inbox
- Vérifier dossier spam
- Tester lien de désabonnement


## BONNES PRATIQUES

### ✅ À FAIRE
- Toujours inclure lien désabonnement
- Utiliser template HTML responsive
- Tester sur plusieurs clients email (Gmail, Outlook, etc.)
- Limiter fréquence envois (max 1-2 fois/semaine)
- Segmenter par catégories
- Personnaliser contenu

### ❌ À ÉVITER
- Envoyer trop souvent (spam)
- Acheter listes emails
- Envoyer sans consentement
- Oublier lien désabonnement
- Utiliser mots spam ("GRATUIT!!!", "GAGNEZ", etc.)


## DÉPANNAGE

### Erreur "Authentication failed"
- Vérifier username/password
- Vérifier App Password (Gmail)
- Vérifier validation 2 étapes activée

### Emails arrivent en spam
- Configurer SPF/DKIM (avancé)
- Utiliser service professionnel (Sendinblue, Mailgun)
- Éviter mots spam
- Demander aux utilisateurs d'ajouter à contacts

### Timeout/Connection refused
- Vérifier port (587 ou 465)
- Vérifier firewall
- Essayer autre serveur SMTP


## MIGRATION VERS SOLUTION PROFESSIONNELLE (Plus tard)

Quand > 1000 abonnés, considérer :
- **Mailchimp** : 500 contacts gratuit, puis 13€/mois
- **Sendinblue** : 300/jour gratuit, puis 19€/mois illimité
- **SendGrid** : 100/jour gratuit, puis 15$/mois
- **Mailjet** : 200/jour gratuit, puis 9€/mois


## RECOMMANDATION FINALE

**Pour démarrer** : Gmail avec App Password
- Gratuit
- Simple
- 500 emails/jour suffisant
- Configuration en 5 minutes

**Pour croître** : Sendinblue
- 300/jour gratuit
- Statistiques incluses
- Professionnalisation
- Upgrade facile
