# Backend — Suivi consommation et habitudes (flow de validation)

Sous-ensemble de `Spec Backend.dc.html` : auth + `GET /me/dashboard` + les
deux écritures qui l'alimentent (`POST /entries`, `POST /habits/{id}/log`).
Le reste des entités (Substances/Habits en CRUD complet, Goals, Rewards,
Partners, Reminders, rapport WhatsApp) suit dans une prochaine passe une fois
cette architecture validée.

## Lancer en local

```bash
cd backend
python3 -m venv venv && source venv/bin/activate   # Python 3.11 ou 3.12 (pas 3.14 : wheels manquants)
pip install -r requirements.txt

uvicorn app.main:app --reload
```

Au démarrage, le serveur met le schéma à jour (migrations Alembic) et crée
le compte de démo `demo@example.com` / `motdepasse123` s'il n'existe pas
(désactivable avec `SEED_DEMO=0`).

## Base de données et migrations

- **Local** : SQLite `suivi.db` par défaut. **En ligne** : Postgres Neon via
  `DATABASE_URL`.
- Le schéma est géré par **Alembic** (`migrations/versions/`), appliqué
  automatiquement au démarrage par `app/migrate.py` — le plan gratuit de
  Render n'a pas de shell pour lancer une commande à part.
- Une base créée avant Alembic (ancien `create_all` + `ALTER TABLE`) est
  reconnue, complétée puis marquée à la révision `0001` : pas de perte de
  données.
- **Modifier le schéma** : changer `app/models.py`, puis
  `alembic revision --autogenerate -m "description"`, relire le fichier
  généré, et vérifier avec `alembic check` (doit répondre "No new upgrade
  operations detected").

## En ligne (Render)

Service `Suivi-back-end` (https://suivi-back-end.onrender.com), redéployé
à chaque push sur `main`. Variables à définir dans Render :

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | URL de connexion Neon (`postgresql://...?sslmode=require`) |
| `JWT_SECRET` | valeur aléatoire — le serveur refuse de démarrer sans |
| `BACKEND_BASE_URL` | `https://suivi-back-end.onrender.com` (redirections OAuth) |

Pas de compte de démo en ligne : crée ton compte depuis l'app.

L'API tourne sur `http://localhost:8000`. Doc interactive auto-générée sur
`http://localhost:8000/docs`.

## Vérifier rapidement sans l'app mobile

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","password":"motdepasse123"}'
# → récupère access_token

curl http://localhost:8000/me/dashboard \
  -H "Authorization: Bearer <access_token>"
```

## Connexions externes (Google Calendar / Outlook)

Scaffold OAuth2 prêt dans `app/routers/integrations.py` — copie
`.env.example` en `.env`, remplis les identifiants (instructions détaillées
en haut du fichier `integrations.py`), et `python-dotenv` les charge
automatiquement au démarrage. Sans ces identifiants, les endpoints
répondent une erreur 501 claire plutôt que de planter.

## Recherche d'aliments (USDA FoodData Central)

`app/routers/food_search.py` — remplace l'ancien import MyFitnessPal
(API fermée aux nouveaux développeurs) et Nutritionix (a supprimé son
offre gratuite, vérifié en juillet 2026) par une recherche dans la base
nutritionnelle ouverte USDA FoodData Central, gratuite sans limite de
temps. Ajoute `FDC_API_KEY` dans `.env` (instructions en haut du fichier ;
`DEMO_KEY` fonctionne pour tester avec un débit plus bas).

## Estimation de calories par photo

`app/routers/meal_photo.py` — deux fournisseurs au choix, jamais appelés en
vrai faute de clés API dans cet environnement :
- **LogMeal** (par défaut, précis, payant au-delà de l'essai gratuit)
- **Gemini + FatSecret** (gratuite : Gemini identifie le plat, FatSecret
  cherche ses calories) — active-la avec `MEAL_PHOTO_PROVIDER=gemini_fatsecret`
  dans `.env`, ou surcharge au cas par cas avec `?provider=gemini_fatsecret`
  sur l'appel sans toucher au réglage par défaut.

Toutes les instructions d'inscription (LogMeal, Gemini, FatSecret) sont en
commentaire en haut du fichier. Un point à vérifier toi-même à la première
utilisation réelle : le chemin exact du champ "calories" dans la réponse
LogMeal (`_extract_logmeal_calories`, TODO explicite dans le code) — je
n'ai pas pu confirmer ce détail précis sans un vrai appel API. Le chemin
Gemini + FatSecret, lui, a été vérifié avec la doc officielle à jour.

## Ce qui est volontairement simplifié dans ce premier flow

- **Pas encore implémenté** : refresh token blacklisting, `/devices` (push),
  paliers santé (`/benefits`, spec §3.2), objectifs récurrents avec
  expiration de période (spec §3.4.1 — actuellement `completed_at` non nul
  = compté, sans notion d'expiration), catalogue de récompenses et achats
  (`/rewards`), partage avec un proche, rapport WhatsApp.
- **Substance.category** (`alcohol`/`tobacco`/`other`) est une extension par
  rapport à la spec fournie — nécessaire pour que le dashboard sache quelles
  substances afficher dans les deux compteurs dédiés de la carte "Série en
  cours". À documenter dans la spec si ce choix est validé côté produit.

## Non testé en conditions réelles

Ce code a été écrit et relu avec soin, syntaxe vérifiée (`py_compile`), mais
**pas exécuté** faute d'accès réseau dans l'environnement où il a été généré
(impossible d'installer les dépendances). Lance-le en local avec les
commandes ci-dessus et remonte-moi la première erreur si besoin — c'est plus
rapide à corriger qu'à deviner à l'aveugle.
