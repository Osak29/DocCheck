"""
Bloc 2 : Moteur de Regles Metier (Python pur, deterministe).

C'est ICI que vivent toutes les decisions de conformite. Aucune IA :
uniquement des comparaisons de dates, de chaines, et des controles de
completude. Facile a tester unitairement, rapide, 100% previsible.
"""
import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Entreprise, Document, Extraction, Anomalie,
    TypeDocument, StatutDocument, NiveauGravite,
)

# Pieces obligatoires pour qu'un dossier entreprise soit considere complet.
# (a adapter selon le referentiel marches publics / BTP vise)
PIECES_OBLIGATOIRES = [
    TypeDocument.KBIS,
    TypeDocument.URSSAF,
    TypeDocument.ASSURANCE_DECENNALE,
    TypeDocument.RC_PRO,
]


@dataclass
class ResultatRegles:
    status_document: StatutDocument
    anomalies: list[dict] = field(default_factory=list)  # {type, description, gravite}


def _parse_date(date_str: str | None) -> dt.date | None:
    if not date_str:
        return None
    try:
        return dt.date.fromisoformat(date_str)
    except ValueError:
        return None


def evaluer_document(
    document: Document,
    extraction_data: dict,
    entreprise: Entreprise,
    aujourdhui: dt.date | None = None,
) -> ResultatRegles:
    """Regle centrale appliquee a CHAQUE document apres extraction.

    Verifie :
      1. la date d'expiration (expire / a relancer / valide)
      2. la coherence du SIREN extrait vs SIREN declare de l'entreprise
    """
    aujourdhui = aujourdhui or dt.date.today()
    anomalies: list[dict] = []
    status = StatutDocument.VALIDE

    date_expiration = _parse_date(extraction_data.get("date_expiration"))
    siren_extrait = extraction_data.get("siren")

    # --- Regle 1 : expiration ---
    if date_expiration is not None:
        if date_expiration < aujourdhui:
            status = StatutDocument.EXPIRE
            anomalies.append({
                "type": "DOC_EXPIRE",
                "description": (
                    f"Le document '{document.type_doc.value}' a expire le "
                    f"{date_expiration.isoformat()}."
                ),
                "gravite": NiveauGravite.BLOQUANT,
            })
        elif (date_expiration - aujourdhui).days <= settings.alerte_j_moins:
            status = StatutDocument.A_RELANCER
            anomalies.append({
                "type": "DOC_A_RELANCER",
                "description": (
                    f"Le document '{document.type_doc.value}' expire le "
                    f"{date_expiration.isoformat()} "
                    f"(dans {(date_expiration - aujourdhui).days} jours)."
                ),
                "gravite": NiveauGravite.AVERTISSEMENT,
            })
    else:
        anomalies.append({
            "type": "DATE_EXPIRATION_MANQUANTE",
            "description": f"Impossible de lire la date d'expiration sur '{document.type_doc.value}'.",
            "gravite": NiveauGravite.AVERTISSEMENT,
        })

    # --- Regle 2 : coherence SIREN ---
    if siren_extrait and entreprise.siren:
        if siren_extrait.replace(" ", "") != entreprise.siren.replace(" ", ""):
            status = StatutDocument.ANOMALIE
            anomalies.append({
                "type": "SIREN_INCOHERENT",
                "description": (
                    f"SIREN extrait ({siren_extrait}) different du SIREN "
                    f"declare pour l'entreprise ({entreprise.siren})."
                ),
                "gravite": NiveauGravite.BLOQUANT,
            })

    return ResultatRegles(status_document=status, anomalies=anomalies)


def evaluer_completude_dossier(
    entreprise: Entreprise, documents: list[Document]
) -> list[TypeDocument]:
    """Regle 3 : verifie que toutes les pieces obligatoires sont presentes
    (et valides / non expirees) pour l'entreprise. Renvoie la liste des
    pieces manquantes."""
    types_valides = {
        d.type_doc for d in documents
        if d.status in (StatutDocument.VALIDE, StatutDocument.A_RELANCER)
    }
    return [p for p in PIECES_OBLIGATOIRES if p not in types_valides]


def appliquer_resultat(db: Session, document: Document, resultat: ResultatRegles) -> None:
    """Persiste le statut calcule et cree les anomalies associees."""
    document.status = resultat.status_document

    for a in resultat.anomalies:
        db.add(Anomalie(
            entreprise_id=document.entreprise_id,
            document_id=document.id,
            type_anomalie=a["type"],
            description=a["description"],
            niveau_gravite=a["gravite"],
        ))

    db.add(document)
    db.commit()


def synchroniser_anomalies_completude(db: Session, entreprise: Entreprise) -> list[TypeDocument]:
    """Recalcule la completude du dossier et cree une anomalie DOC_MANQUANT
    pour chaque piece obligatoire absente (idempotent : ne duplique pas si
    deja signalee et non resolue)."""
    manquantes = evaluer_completude_dossier(entreprise, entreprise.documents)

    deja_signalees = {
        a.type_anomalie.replace("DOC_MANQUANT_", "")
        for a in entreprise.anomalies
        if a.type_anomalie.startswith("DOC_MANQUANT_") and not a.resolue
    }

    for piece in manquantes:
        if piece.value not in deja_signalees:
            db.add(Anomalie(
                entreprise_id=entreprise.id,
                document_id=None,
                type_anomalie=f"DOC_MANQUANT_{piece.value}",
                description=f"Piece obligatoire manquante : {piece.value}.",
                niveau_gravite=NiveauGravite.BLOQUANT,
            ))
    db.commit()
    return manquantes
