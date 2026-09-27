# Données personnelles : inventaire pour Google Play (Data safety, Health apps)

App publiée sous le nom **Tanren** (dépôts `Suivi-back-end` / `Suivi-mobile`).
Pages publiques servies par le backend : `/legal/privacy.html` (raccourci
`/privacy`), `/legal/delete-account.html` (raccourci `/delete-account`),
`/compte/suppression`. Sources des deux premières : `app/legal/`, reprises du
kit de publication (`suivi-app/publication/tanren-kit/`) et corrigées pour
coller au code ; l'adresse de contact vient de la variable `CONTACT_EMAIL`.

État du code au 27/09/2026 (backend `Suivi-back-end`, app `Suivi-mobile`). Ce
document sert à remplir le formulaire **Data safety** et la déclaration
**Health apps** de la Play Console. Il décrit ce que fait le code : les points
marqués **À confirmer** dépendent d'un réglage hors code (contrat, console d'un
fournisseur) et doivent être vérifiés avant de répondre.

## 1. Où vivent les données

| Élément | Service | Région actuelle | Remarque |
|---|---|---|---|
| API | Render (service `Suivi-back-end`) | **Ohio (États-Unis)** | Déménagement à Francfort prévu (lot C de l'audit) |
| Base de données | Neon Postgres | **AWS US East 2 (États-Unis)** | Passage en UE prévu (lot C). Chiffrement au repos : **À confirmer** dans la documentation Neon de l'offre choisie |
| Mises à jour de l'app | Expo (EAS Update, `u.expo.dev`) | — | Code de l'app uniquement, aucune donnée utilisateur |

Tout échange app ↔ API passe en HTTPS (Render impose TLS). Les mots de passe
sont hachés (bcrypt, `app/security.py`), jamais stockés en clair. Les jetons
de réinitialisation et de suppression sont stockés hachés (SHA-256).

Tant que l'hébergement reste aux États-Unis, les données de santé d'utilisateurs
européens quittent l'UE : à régler (lot C) avant le test fermé, ou à mentionner
dans la politique de confidentialité.

## 2. Données collectées (stockées côté serveur)

| Catégorie Play Console | Données | Tables | Obligatoire ? | Finalité |
|---|---|---|---|---|
| Informations personnelles → Adresse e-mail | e-mail du compte | `users` | Oui | Compte, connexion, e-mails de réinitialisation |
| Informations personnelles → Nom | nom affiché | `users` | Non | Personnalisation |
| Informations personnelles → Numéro de téléphone | numéro WhatsApp du rapport | `report_settings` | Non | Pré-remplir le partage du rapport (le message part par le partage du téléphone, pas par le serveur) |
| Santé et remise en forme → Informations de santé | cycle menstruel, règles, flux, contraception | `cycle_settings`, `cycle_logs`, `cycle_flow_entries` | Non | Suivi du cycle |
| Santé et remise en forme → Informations de santé | consommation d'alcool et de tabac, habitudes à perdre, humeur associée | `substances`, `consumption_entries`, `bad_habits` | Non | Suivi et arrêt des consommations |
| Santé et remise en forme → Informations de santé | poids, masse grasse, objectif de poids, taille, âge, sexe (profil) | `weight_entries`, `body_fat_entries`, `profiles` | Non | Budget calorique, suivi du poids |
| Santé et remise en forme → Informations de remise en forme | séances (course, muscu, autres sports, étirements/yoga), pas, sommeil, fréquence cardiaque des séances | `runs`, `strength_sessions`, `other_sport_logs`, `flexibility_sessions`, `daily_steps`, `sleep_logs` | Non | Suivi sportif, calories dépensées |
| Santé et remise en forme → Informations de santé | repas, calories, macros, plan alimentaire, stock du placard | `meals`, `meal_plan_entries`, `pantry_items`, `cooking_logs` | Non | Suivi nutritionnel |
| Activité dans l'app → Autres actions | habitudes et leurs coches, objectifs, récompenses, journal, cartes de révision | `habits`, `habit_logs`, `goals`, `rewards`, `flash_cards`... | Non | Fonctions de l'app |
| Informations personnelles → Autres | lien de partage avec un proche (son compte, rappels envoyés) | `partner_links`, `partner_reminders` | Non | Partage des progrès |
| Identifiants d'accès tiers | jetons OAuth Google Agenda / Outlook | `external_integrations` | Non | Synchro des habitudes avec l'agenda. **Stockés en clair aujourd'hui** : chiffrement prévu (lot B) |

Aucune donnée n'est vendue, ni utilisée pour de la publicité. Il n'y a ni
publicité ni outil d'analyse d'audience dans l'app à ce jour (PostHog prévu au
lot F : à ajouter à ce document ce jour-là).

## 3. Données envoyées à des tiers pour traitement

Au sens de Google Play, un transfert à un prestataire qui traite la donnée
pour le compte de l'app n'est pas un « partage » ; il faut en revanche le
décrire dans la politique de confidentialité.

| Tiers | Ce qui part | Quand | Conservé par l'app ? |
|---|---|---|---|
| Google Gemini (`generativelanguage.googleapis.com`) | photo d'un repas ; photo du frigo / placard ; photo d'un ticket de courses | à chaque analyse demandée par l'utilisateur | Non : la photo n'est pas enregistrée par le backend, seul le résultat relu l'est. Conservation chez Google selon l'offre de la clé API (offre gratuite : Google peut conserver et relire les contenus) : **À confirmer** avant publication |
| FatSecret Platform | nom du plat reconnu (texte) | estimation de calories d'une photo | Non |
| LogMeal (option payante) | photo d'un repas | si l'utilisateur choisit ce fournisseur | Non |
| USDA FoodData Central | texte de recherche d'aliment | recherche d'aliment | Non |
| TheMealDB | texte de recherche de recette | recherche de recette externe | Non |
| Google (OAuth, Agenda) / Microsoft (OAuth, Outlook) | jetons OAuth, créneaux des habitudes | si l'utilisateur connecte son agenda | Jetons conservés (voir §2) |
| Brevo ou Resend | adresse e-mail et contenu du message | mot de passe oublié, confirmation de suppression | Non |
| YouTube (lecteur intégré, domaine sans cookies `youtube-nocookie.com`) | adresse IP, vidéo regardée | mode Vidéo du module Souplesse | Non |

## 4. Health Connect (déclaration Health apps)

Lecture seule, sur demande explicite de l'utilisateur (Paramètres → Montre),
`mobile/src/health.js` :

| Type Health Connect | Usage |
|---|---|
| `ExerciseSession` | importer les séances de sport faites avec la montre |
| `Steps`, `Distance` | pas du jour, distance des séances |
| `ActiveCaloriesBurned` | calories dépensées par séance |
| `HeartRate` | fréquence cardiaque moyenne et max d'une séance |
| `SleepSession` | durée de sommeil |
| `Weight` | courbe de poids |

Aucune écriture dans Health Connect. Les données lues sont envoyées au backend
pour être affichées dans l'historique et les statistiques (tables §2).

## 5. Droits de l'utilisateur

- **Suppression du compte et de toutes les données** : dans l'app (Paramètres →
  Compte → Supprimer mon compte, mot de passe redemandé) et sur le web, sans
  l'app : `https://suivi-back-end.onrender.com/compte/suppression` (lien de
  confirmation envoyé par e-mail, valable 30 minutes). Suppression immédiate
  et définitive de toutes les tables (`app/services/compte.py`, vérifié par
  `tests/test_suppression_compte.py`). Aucune sauvegarde n'est conservée par
  l'app ; les sauvegardes automatiques de Neon (historique de restauration)
  gardent les données jusqu'à leur expiration : **durée à confirmer** selon
  l'offre Neon, et à indiquer dans la politique de confidentialité.
- **Mot de passe oublié** : lien à usage unique par e-mail (30 minutes).
- Suppression des données d'un seul module (cycle notamment) : prévue avec le
  passage en modules (lot D).

## 6. Réponses probables au formulaire Data safety

- Collecte de données : **Oui** (voir §2).
- Partage avec des tiers : **Non** au sens de Google Play (prestataires
  uniquement, §3), à confirmer pour Gemini selon l'offre de la clé API.
- Données chiffrées en transit : **Oui**.
- Possibilité de demander la suppression : **Oui**, dans l'app et sur le web.
- Données de santé : cycle, consommations, poids, sport, sommeil, nutrition →
  cocher « Informations de santé » et « Informations de remise en forme ».
