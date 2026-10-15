# DocCheck — Documentation du projet

Plateforme hybride d'audit et de contrôle documentaire (BTP) : extraction structurée par IA, validation par un moteur de règles déterministe, suivi de conformité en base de données, dashboard de pilotage.

## Architecture

```
PDF / Scan (texte ou image)
      │
      ▼
1. Extraction (app/extraction.py)      → JSON structuré (Claude, tool-use forcé, ou mock par regex)
      │
      ▼
2. Moteur de règles (app/rules_engine.py) → statuts + anomalies (Python pur, déterministe)
      │
      ▼
3. Base de données (app/models.py)     → PostgreSQL (Supabase) via SQLAlchemy
      │
      ▼
4. API + Dashboard + Automatisation    → FastAPI, Streamlit, APScheduler
```

**Principe clé :** l'IA ne fait **aucune** déduction métier — elle lit uniquement le document et remplit un schéma JSON strict. Toute décision (expiré ? cohérent ? complet ?) est calculée par du code Python déterministe dans `rules_engine.py`, donc testable, rapide et prévisible.

## Structure des fichiers

| Fichier | Rôle |
| --- | --- |
| `app/config.py` | Configuration centralisée (variables d'environnement) |
| `app/database.py` | Connexion SQLAlchemy, création des tables |
| `app/models.py` | Schéma BDD : `entreprises`, `documents`, `extractions`, `anomalies` |
| `app/schemas.py` | Schémas Pydantic (API + extraction LLM) |
| `app/extraction.py` | Appel à Claude (tool-use) ou mock par regex |
| `app/rules_engine.py` | Règles de conformité (expiration, SIREN, complétude) |
| `app/main.py` | API FastAPI (endpoints) |
| `app/tasks.py` | Job nocturne : recalcul des statuts + relances simulées |
| `dashboard/streamlit_app.py` | Dashboard de suivi (upload, OCR, vue par dossier) |
| `doccheck_schema.sql` | Script SQL pour créer le schéma sur Supabase |
| `sanity_check.py` | Script de test end-to-end (sans clé API) |

## Installation et lancement

1. `python -m venv venv` puis activer l'environnement
2. `pip install -r requirements.txt`
3. Copier `.env.example` en `.env` et renseigner `DATABASE_URL` (Supabase, connexion directe port 5432 recommandée) et, en option, `ANTHROPIC_API_KEY`
4. `uvicorn app.main:app --reload` → crée les tables automatiquement au démarrage si elles n'existent pas (ou exécuter `doccheck_schema.sql` directement dans Supabase au préalable)
5. Dans un second terminal : `streamlit run dashboard/streamlit_app.py`
6. Optionnel — OCR des PDF scannés : installer Tesseract OCR + Poppler, `pip install pytesseract pdf2image`, et renseigner `TESSERACT_CMD` / `POPPLER_PATH` en haut de `streamlit_app.py`

## Variables d'environnement (`.env`)

| Variable | Rôle | Obligatoire |
| --- | --- | --- |
| `DATABASE_URL` | Connexion PostgreSQL (Supabase) | Oui |
| `ANTHROPIC_API_KEY` | Active la vraie extraction IA (Claude). Si vide, bascule automatiquement sur un mock par regex | Non |
| `ANTHROPIC_MODEL` | Modèle Claude utilisé | Non (défaut fourni) |
| `ALERTE_J_MOINS` | Seuil en jours avant expiration pour passer un document en "à relancer" | Non (défaut 30) |
| `API_BASE_URL` | URL de l'API, utilisée par le dashboard | Non |

## Modèle de données

- **entreprises** : `id`, `nom`, `siren`, `email_contact`
- **documents** : `id`, `entreprise_id`, `type_doc` (enum : KBIS, ATTESTATION\_URSSAF, ASSURANCE\_DECENNALE, RC\_PRO, ATTESTATION\_FISCALE, AUTRE), `texte_source`, `status` (enum : EN\_ATTENTE, VALIDE, A\_RELANCER, EXPIRE, ANOMALIE)
- **extractions** : résultat structuré de l'IA pour un document (SIREN extrait, dates, montant, confiance, JSON brut)
- **anomalies** : `type_anomalie`, `description`, `niveau_gravite` (INFO, AVERTISSEMENT, BLOQUANT), `resolue`

## Endpoints API principaux

| Méthode | Route | Rôle |
| --- | --- | --- |
| POST | `/entreprises` | Créer une entreprise |
| GET | `/entreprises` | Lister les entreprises |
| GET | `/entreprises/{id}/dossier` | Vue synthétique de conformité (documents + anomalies + pièces manquantes) |
| POST | `/documents` | Uploader un document (texte déjà extrait) |
| POST | `/documents/{id}/traiter` | Lance extraction IA + règles + recalcul de complétude |
| GET | `/documents` | Lister les documents |
| GET | `/documents/{id}/extraction` | Détail de l'extraction d'un document |
| GET | `/anomalies` | Lister les anomalies (filtrable par `resolue`) |
| POST | `/anomalies/{id}/resoudre` | Marquer une anomalie comme résolue |

Documentation interactive complète (Swagger) disponible sur `/docs` une fois l'API lancée.

## Règles métier implémentées

1. **Expiration** : un document passe en `A_RELANCER` dans la fenêtre `ALERTE_J_MOINS`, puis en `EXPIRE` une fois la date dépassée
2. **Cohérence SIREN** : le SIREN extrait du document est comparé au SIREN déclaré de l'entreprise ; une divergence crée une anomalie `BLOQUANT`
3. **Complétude du dossier** : vérifie que les pièces obligatoires (KBIS, URSSAF, assurance décennale, RC Pro) sont présentes et valides ; sinon anomalie `DOC_MANQUANT_*`

Le job nocturne (`app/tasks.py`) ré-applique ces règles chaque jour pour faire évoluer les statuts dans le temps, et simule l'envoi de relances (webhook/email) — voir limites ci-dessous.

## Éléments manquants / limites connues

Ce projet est un socle fonctionnel validé de bout en bout, mais plusieurs points restent à compléter avant une mise en production :

- **Pas d'authentification ni d'autorisation sur l'API** : tous les endpoints sont ouverts, sans notion d'utilisateur ou de rôle. À ajouter avant tout déploiement public (OAuth2, API key, ou intégration Supabase Auth).
- **Pas de vraies relances** : `envoyer_relance()` dans `app/tasks.py` ne fait que logger l'intention ; aucun email ou webhook n'est réellement envoyé. Il faut brancher un vrai provider (SendGrid, Make, Slack...).
- **Stockage des fichiers sources non implémenté** : le champ `url_file` existe dans le modèle mais n'est jamais rempli ; les PDF originaux ne sont pas conservés (seul le texte extrait l'est). Prévoir un upload vers Supabase Storage ou S3 si l'archivage des originaux est requis.
- **Pas de migrations de schéma** : `init_db()` utilise `Base.metadata.create_all`, qui crée les tables si absentes mais ne gère ni les évolutions de schéma ni les rollbacks. Passer à Alembic dès que le schéma doit évoluer en production.
- **Pas de tests automatisés** : seul `sanity_check.py` existe (script manuel). Aucune suite de tests unitaires (pytest) sur `rules_engine.py`, pourtant le composant le plus critique à fiabiliser.
- **OCR limité** : `pytesseract` est configuré en français uniquement (`lang="fra"`) ; la qualité dépend fortement de la résolution/netteté du scan, sans prétraitement d'image (redressement, contraste, suppression de bruit).
- **Le score de confiance de l'extraction (`confiance`) est stocké mais inutilisé** : le moteur de règles ne tient pas compte de ce score pour, par exemple, forcer une revue manuelle en cas de confiance basse.
- **Pas de pagination** sur les listings (`/documents`, `/anomalies`, `/entreprises`) : problématique dès que le volume de données grossit.
- **CORS non configuré** : si le dashboard ou un futur frontend tourne sur un domaine différent de l'API, il faudra ajouter le middleware CORS de FastAPI.
- **Dashboard limité en édition** : impossible de modifier ou supprimer une entreprise/un document depuis l'interface ; uniquement création et consultation.
- **Row Level Security (RLS) désactivé sur Supabase** : le backend utilise le rôle `postgres` qui contourne le RLS. Si d'autres canaux (API Supabase, client JS) doivent accéder aux données, des policies RLS restent à écrire.
- **`docker-compose.yml` non testé en conditions réelles** : la configuration (Postgres + API + worker + dashboard) a été écrite mais pas validée par un build/run complet.
- **Pas de CI/CD, logging structuré, ni monitoring** (Sentry, logs centralisés) : utile avant un vrai déploiement.

## Prochaines étapes suggérées

Par ordre de priorité raisonnable pour une mise en production progressive :

1. Ajouter des tests unitaires sur `rules_engine.py` (le cœur métier)
2. Authentification sur l'API
3. Vraies relances (email/webhook)
4. Stockage des fichiers sources + migrations Alembic
5. CI/CD basique + monitoring
