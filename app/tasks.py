"""
Bloc 4bis : Automatisation.

Job nocturne (CRON / APScheduler) qui :
  1. Re-applique le moteur de regles a tous les documents (fait avancer les
     statuts EN_ATTENTE -> ... -> A_RELANCER -> EXPIRE au fil du temps)
  2. Simule l'envoi d'un webhook/email de relance pour chaque document en
     A_RELANCER ou EXPIRE dont l'entreprise a une adresse de contact.

Lancement ponctuel :  python -m app.tasks
Lancement en demon (planifie chaque nuit a 2h) : python -m app.tasks --daemon
"""
import argparse
import datetime as dt
import logging

import requests
from apscheduler.schedulers.blocking import BlockingScheduler

from app.config import settings
from app.database import SessionLocal, init_db
from app import models, rules_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def envoyer_relance(entreprise: "models.Entreprise", document: "models.Document") -> None:
    """Simule l'envoi d'une notification de relance (webhook/email).

    En prod, remplace ce POST par un vrai appel a un provider (SendGrid,
    Make/Zapier, Slack, Teams...). Ici on illustre le principe avec un
    webhook generique configurable.
    """
    payload = {
        "entreprise": entreprise.nom,
        "siren": entreprise.siren,
        "email": entreprise.email_contact,
        "document": document.type_doc.value,
        "statut": document.status.value,
        "message": (
            f"Le document '{document.type_doc.value}' de {entreprise.nom} "
            f"necessite une action ({document.status.value})."
        ),
    }
    logger.info("[RELANCE SIMULEE] %s", payload)
    # Exemple d'appel reel (decommenter et configurer une URL de webhook) :
    # requests.post(settings.webhook_url, json=payload, timeout=5)


def executer_verification_nocturne() -> dict:
    """Point d'entree du job : recalcule statuts + declenche les relances.
    Retourne un petit rapport (utile pour logs / tests)."""
    init_db()
    db = SessionLocal()
    rapport = {"documents_verifies": 0, "relances_envoyees": 0, "anomalies_creees": 0}

    try:
        documents = (
            db.query(models.Document)
            .filter(models.Document.status != models.StatutDocument.EN_ATTENTE)
            .all()
        )
        for document in documents:
            extraction = document.extraction
            if not extraction:
                continue

            data = {
                "date_expiration": extraction.date_expiration.date().isoformat()
                if extraction.date_expiration else None,
                "siren": extraction.siren_extrait,
            }
            entreprise = document.entreprise
            resultat = rules_engine.evaluer_document(document, data, entreprise)

            ancien_statut = document.status
            rules_engine.appliquer_resultat(db, document, resultat)
            rapport["documents_verifies"] += 1
            rapport["anomalies_creees"] += len(resultat.anomalies)

            if document.status in (models.StatutDocument.A_RELANCER, models.StatutDocument.EXPIRE):
                if entreprise.email_contact:
                    envoyer_relance(entreprise, document)
                    rapport["relances_envoyees"] += 1

            if ancien_statut != document.status:
                logger.info(
                    "Document %s : %s -> %s", document.id, ancien_statut.value, document.status.value
                )

        # Recalcule aussi la completude de chaque dossier
        for entreprise in db.query(models.Entreprise).all():
            rules_engine.synchroniser_anomalies_completude(db, entreprise)

    finally:
        db.close()

    logger.info("Rapport verification nocturne : %s", rapport)
    return rapport


def lancer_demon():
    scheduler = BlockingScheduler(timezone="Europe/Paris")
    scheduler.add_job(executer_verification_nocturne, "cron", hour=2, minute=0)
    logger.info("Demon de verification demarre (tous les jours a 02:00 Europe/Paris).")
    scheduler.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DocCheck - job de verification/relance")
    parser.add_argument("--daemon", action="store_true", help="Lance en planificateur continu")
    args = parser.parse_args()

    if args.daemon:
        lancer_demon()
    else:
        executer_verification_nocturne()
