# JAP Tool — Tournoi Padel FFT
Application web de gestion de tournois Padel FFT.

## Stack
- Python Flask
- ReportLab + pypdf (génération PDF)
- Twilio (envoi SMS)
- Coolify (déploiement)

## Déploiement sur Coolify
1. Connecter le repo GitHub
2. Définir obligatoirement `APP_ENV=production` et une `SECRET_KEY` longue et aléatoire
3. Ajouter les variables d'environnement Twilio
4. Si Coolify transmet les adresses IP via proxy, définir `TRUST_PROXY_HEADERS=true`
5. Pour un premier démarrage sur une base vide uniquement, fournir temporairement
   `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` et éventuellement
   `BOOTSTRAP_ADMIN_NAME`, puis retirer ces variables après création du compte
6. Domaine : jap.myconvi.fr

### Variables Twilio

- `TWILIO_SID`
- `TWILIO_TOKEN`
- `TWILIO_FROM`
- `TWILIO_WHATSAPP_FROM`
- `TWILIO_WHATSAPP_TEMPLATE_SID`
- `TWILIO_WEBHOOK_URL`
- `TWILIO_REPLY_REDIRECT_TO`

Les identifiants Twilio restent côté serveur et ne doivent jamais être saisis ou
stockés dans le navigateur.

## Usage
1. Uploader le CSV FFT (Inscriptions-Tableau_X.csv)
2. Configurer le tournoi
3. Cliquer "Générer"
4. Télécharger les PDFs ou envoyer les SMS

## Tests

```bash
python -m unittest discover -s tests -v
```

Les tests utilisent une base SQLite temporaire et ne touchent pas la production.

Pour un lancement local en HTTP, utiliser `SESSION_COOKIE_SECURE=false`. Cette
option ne doit pas être utilisée sur le domaine de production en HTTPS.
