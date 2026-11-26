# HAIDARA AI v2

Interface blanche style Grok + Gemini 3.8 Flash + système de crédits Orange Money (Guinée).

## Fonctionnalités

- Interface claire, blanche, parfaitement responsive (PC + iPhone)
- 10 messages gratuits par utilisateur
- Pack payant : **50 messages = 20 000 GNF**
- Paiement via Orange Money au numéro **629600906**
- Validation des paiements via page admin
- Historique des conversations (localStorage)
- Appels Gemini fiables avec gestion d’erreurs

## Déploiement sur Render (recommandé)

### 1. Préparer le dépôt

Crée un dépôt GitHub et mets tous les fichiers de ce dossier dedans.

### 2. Créer un nouveau Web Service sur Render

1. Va sur [render.com](https://render.com) → **New** → **Web Service**
2. Connecte ton dépôt GitHub
3. Configure :
   - **Runtime** : Python 3
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Environment Variables** (obligatoires) :

| Variable | Valeur |
|----------|--------|
| `GEMINI_API_KEY` | Ta clé API Gemini |
| `GEMINI_MODEL` | `gemini-3.8-flash` |
| `ADMIN_PASSWORD` | Un mot de passe fort (ex: `MonMotDePasseSecret2026`) |
| `DATABASE_PATH` | `/opt/render/project/src/haidara.db` (optionnel) |

5. Clique sur **Create Web Service**

### 3. Après le déploiement

- Site public : `https://ton-service.onrender.com`
- Page admin : `https://ton-service.onrender.com/admin`

## Utilisation du système de paiement

1. L’utilisateur clique sur **Acheter des messages** (ou épuise ses 10 messages gratuits)
2. Il choisit :
   - **Standard** → 50 messages pour 20 000 GNF
   - **Premium** → 200 messages + badge Premium pour 50 000 GNF
3. Une référence unique est générée (ex: `HAIDARA-A1B2C3D4`)
4. L’utilisateur envoie le montant au **+224 629 600 906** en mettant la référence comme motif
5. Il entre le **code de transaction** Orange Money dans l’application
6. Toi (admin) :
   - Va sur `/admin`
   - Entre ton mot de passe
   - Clique sur **Valider** → les crédits (et le statut Premium si applicable) sont ajoutés immédiatement

## Développement local

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="ta_clé"
export ADMIN_PASSWORD="test123"
uvicorn main:app --reload --port 8000
```

Ouvre http://localhost:8000

## Notes importantes

- Sur le plan **gratuit** de Render, le disque est éphémère : les données (crédits, paiements) peuvent être perdues si le service redémarre longtemps. Pour la production, passe sur un plan payant ou ajoute une base PostgreSQL gratuite (Neon, Supabase…).
- Change absolument le `ADMIN_PASSWORD` !
- Le modèle par défaut est `gemini-3.8-flash`. Tu peux le changer via la variable `GEMINI_MODEL`.

## Structure

```
haidara-ai/
├── main.py              # Backend FastAPI
├── requirements.txt
├── templates/
│   ├── index.html       # Interface utilisateur (style Grok)
│   └── admin.html       # Page d’administration des paiements
└── README.md
```

Bon succès avec HAIDARA AI !
