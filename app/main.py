"""
Bloc 4 : Backend FastAPI.

Expose les endpoints d'upload, d'extraction/validation, et de consultation
des dossiers de conformite. Volontairement mince : toute la logique vit dans
`rules_engine.py` et `extraction.py`.
"""
import datetime as dt
import logging

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app import models, schemas
from app.extraction import get_extraction_client
from app import rules_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DocCheck API",
    description="Plateforme hybride d'audit et de controle documentaire (BTP)",
    version="0.1.0",
)


@app.on_event("startup")
def on_startup():
    init_db()


# ---------------------------------------------------------------------------
# Entreprises
# ---------------------------------------------------------------------------
@app.post("/entreprises", response_model=schemas.EntrepriseOut)
def creer_entreprise(payload: schemas.EntrepriseCreate, db: Session = Depends(get_db)):
    entreprise = models.Entreprise(**payload.model_dump())
    db.add(entreprise)
    db.commit()
    db.refresh(entreprise)
    return entreprise


@app.get("/entreprises", response_model=list[schemas.EntrepriseOut])
def lister_entreprises(db: Session = Depends(get_db)):
    return db.query(models.Entreprise).all()


@app.get("/entreprises/{entreprise_id}/dossier", response_model=schemas.DossierConformite)
def dossier_entreprise(entreprise_id: int, db: Session = Depends(get_db)):
    entreprise = db.get(models.Entreprise, entreprise_id)
    if not entreprise:
        raise HTTPException(404, "Entreprise introuvable")

    manquantes = rules_engine.evaluer_completude_dossier(entreprise, entreprise.documents)
    anomalies_non_resolues = [a for a in entreprise.anomalies if not a.resolue]

    return schemas.DossierConformite(
        entreprise=entreprise,
        documents=entreprise.documents,
        anomalies=entreprise.anomalies,
        conforme=(len(manquantes) == 0 and len(anomalies_non_resolues) == 0),
        pieces_manquantes=manquantes,
    )


# ---------------------------------------------------------------------------
# Documents : upload + pipeline extraction -> regles
# ---------------------------------------------------------------------------
@app.post("/documents", response_model=schemas.DocumentOut)
def uploader_document(payload: schemas.DocumentCreate, db: Session = Depends(get_db)):
    entreprise = db.get(models.Entreprise, payload.entreprise_id)
    if not entreprise:
        raise HTTPException(404, "Entreprise introuvable")

    document = models.Document(
        entreprise_id=payload.entreprise_id,
        type_doc=payload.type_doc,
        texte_source=payload.texte_source,
        status=models.StatutDocument.EN_ATTENTE,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@app.post("/documents/{document_id}/traiter", response_model=schemas.DocumentOut)
def traiter_document(document_id: int, db: Session = Depends(get_db)):
    """Lance le pipeline complet sur un document :
    1. Extraction IA (JSON structure)
    2. Application du moteur de regles
    3. Recalcul de la completude du dossier
    """
    document = db.get(models.Document, document_id)
    if not document:
        raise HTTPException(404, "Document introuvable")
    entreprise = document.entreprise

    # 1. Extraction
    client = get_extraction_client()
    resultat_llm = client.extract(document.texte_source or "")
    data = resultat_llm.model_dump()

    def parse_dt(s):
        return dt.datetime.fromisoformat(s) if s else None

    extraction = models.Extraction(
        document_id=document.id,
        nom_entreprise=data.get("nom_entreprise"),
        siren_extrait=data.get("siren"),
        date_emission=parse_dt(data.get("date_emission")),
        date_expiration=parse_dt(data.get("date_expiration")),
        montant=data.get("montant"),
        confiance=data.get("confiance"),
        json_raw=data,
    )
    db.add(extraction)
    db.commit()

    # 2. Regles metier (deterministe)
    resultat = rules_engine.evaluer_document(document, data, entreprise)
    rules_engine.appliquer_resultat(db, document, resultat)

    # 3. Completude du dossier entreprise
    rules_engine.synchroniser_anomalies_completude(db, entreprise)

    db.refresh(document)
    return document


@app.get("/documents", response_model=list[schemas.DocumentOut])
def lister_documents(db: Session = Depends(get_db)):
    return db.query(models.Document).all()


@app.get("/documents/{document_id}/extraction", response_model=schemas.ExtractionOut)
def extraction_document(document_id: int, db: Session = Depends(get_db)):
    extraction = db.query(models.Extraction).filter_by(document_id=document_id).first()
    if not extraction:
        raise HTTPException(404, "Aucune extraction pour ce document")
    return extraction


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------
@app.get("/anomalies", response_model=list[schemas.AnomalieOut])
def lister_anomalies(resolue: bool | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Anomalie)
    if resolue is not None:
        q = q.filter_by(resolue=resolue)
    return q.order_by(models.Anomalie.created_at.desc()).all()


@app.post("/anomalies/{anomalie_id}/resoudre", response_model=schemas.AnomalieOut)
def resoudre_anomalie(anomalie_id: int, db: Session = Depends(get_db)):
    anomalie = db.get(models.Anomalie, anomalie_id)
    if not anomalie:
        raise HTTPException(404, "Anomalie introuvable")
    anomalie.resolue = True
    db.commit()
    db.refresh(anomalie)
    return anomalie


@app.get("/health")
def health():
    return {"status": "ok"}
