# 💳 CONFIGURATION STRIPE — GUIDE COMPLET

## 1. Créer un compte Stripe

1. Allez sur **https://dashboard.stripe.com/register**
2. Créez votre compte (email professionnel recommandé)
3. Vous démarrez automatiquement en **mode Test** (paiements factices, aucun argent réel) — parfait pour vérifier que tout fonctionne avant de passer en réel

## 2. Récupérer les clés API (mode Test d'abord)

1. Dans le Dashboard Stripe, en haut à droite : vérifiez que vous êtes bien en **mode Test** (bascule "Test mode")
2. Menu **Développeurs → Clés API**
3. Copiez :
   - **Clé secrète** (commence par `sk_test_...`)

## 3. Ajouter la clé dans Vercel

**Vercel → votre projet → Settings → Environment Variables** :

| Clé | Valeur |
|---|---|
| `STRIPE_SECRET_KEY` | `sk_test_...` (votre clé secrète copiée) |

Puis **Redeploy** (ou faites un nouveau commit, ce qui redéploie automatiquement).

⚠️ **Tant que `STRIPE_SECRET_KEY` n'est pas configurée, le site fonctionne quand même** : les commandes sont enregistrées normalement, juste sans paiement en ligne (mode dégradé automatique).

## 4. Configurer le webhook (confirmation fiable des paiements)

1. Dans Stripe : **Développeurs → Webhooks → Add endpoint**
2. URL du endpoint : `https://VOTRE-SITE.vercel.app/stripe/webhook`
3. Événements à écouter : cochez uniquement **`checkout.session.completed`**
4. Cliquez **Add endpoint**
5. Une fois créé, cliquez dessus → **Signing secret** → révélez-le (commence par `whsec_...`) → copiez-le

## 5. Ajouter le webhook secret dans Vercel

| Clé | Valeur |
|---|---|
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` |

Redeploy à nouveau.

## 6. Tester en mode Test

1. Ajoutez un produit au panier sur votre site, passez commande
2. Sur la page Stripe qui s'ouvre, utilisez une **carte de test** :
   - Numéro : `4242 4242 4242 4242`
   - Date : n'importe quelle date future
   - CVC : n'importe quel 3 chiffres
3. Le paiement doit réussir, vous êtes redirigé vers votre page de succès avec la confirmation
4. Vérifiez dans **admin → Commandes** que la commande apparaît avec le badge "Payée via Stripe"
5. Vérifiez aussi dans le Dashboard Stripe (**Paiements**) que le paiement test apparaît

## 7. Passer en mode Réel (quand vous êtes prêt à recevoir de vrais paiements)

1. Dans Stripe, complétez les informations de votre entreprise (**Activate your account**) — nécessaire pour recevoir de vrais paiements en France (infos bancaires, SIRET/SIREN ou équivalent, etc.)
2. Une fois activé, basculez le Dashboard en **mode Live** (bascule en haut à droite)
3. Récupérez les **nouvelles clés** (mode Live cette fois : `sk_live_...`)
4. Recréez un **webhook en mode Live** (répéter l'étape 4, mais le Dashboard étant en mode Live cette fois) → nouveau `whsec_...`
5. Remplacez `STRIPE_SECRET_KEY` et `STRIPE_WEBHOOK_SECRET` dans Vercel par les valeurs **Live**
6. Redeploy

⚠️ Les clés Test et Live sont complètement séparées — un paiement test n'apparaît jamais dans le Dashboard en mode Live, et inversement.

## Ce qui est déjà géré par le site

- ✅ Prix toujours recalculés côté serveur depuis la base de données (le prix envoyé par le navigateur n'est **jamais** utilisé directement — protection contre la fraude)
- ✅ Paiement par carte bancaire (Visa, Mastercard, etc.)
- ✅ Confirmation automatique du paiement (double vérification : au retour du client ET via webhook, pour ne rien manquer même si le client ferme son navigateur)
- ✅ Devise : Euro (EUR)
- ✅ Panier vidé uniquement après paiement confirmé
- ✅ Statut de paiement visible dans l'admin (Payée / En attente)

## Pas encore inclus (évolutions possibles)

- Remboursements depuis l'admin (à faire manuellement depuis le Dashboard Stripe pour l'instant)
- Autres moyens de paiement (Apple Pay, Google Pay, virement SEPA) — activables directement dans les réglages Stripe sans changement de code, si vous les activez dans **Paramètres → Méthodes de paiement** sur le Dashboard
- Factures automatiques
