"""
Schemas Pydantic :
- schemas "API" (entree/sortie FastAPI)
- schema "ExtractionLLM" = le JSON strict qu'on force le LLM a produire
  (aucune deduction metier laissee au modele : il ne fait QUE lire le document)
"""
import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models import TypeDocument, StatutDocument, NiveauGravite


# ---------------------------------------------------------------------------
# Extraction LLM (sortie structuree stricte)
# ---------------------------------------------------------------------------
class ExtractionLLM(BaseModel):
    """Schema impose au LLM. Champs a null si non trouves dans le document,
    jamais devines."""
    document_type: Optional[TypeDocument] = Field(
        default=None, description="Type de document identifie"
    )
    nom_entreprise: Optional[str] = Field(default=None)
    siren: Optional[str] = Field(
        default=None, description="9 chiffres, sans espaces"
    )
    date_emission: Optional[str] = Field(default=None, description="Format YYYY-MM-DD")
    date_expiration: Optional[str] = Field(default=None, description="Format YYYY-MM-DD")
    montant: Optional[float] = Field(default=None, description="Montant/plafond si present")
    confiance: float = Field(default=0.5, ge=0, le=1, description="Confiance globale de l'extraction")

    @field_validator("siren")
    @classmethod
    def siren_digits_only(cls, v):
        if v is None:
            return v
        v = v.replace(" ", "")
        return v


# ---------------------------------------------------------------------------
# Entreprises
# ---------------------------------------------------------------------------
class EntrepriseCreate(BaseModel):
    nom: str
    siren: str
    email_contact: Optional[str] = None


class EntrepriseOut(BaseModel):
    id: int
    nom: str
    siren: str
    email_contact: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentCreate(BaseModel):
    entreprise_id: int
    type_doc: TypeDocument
    texte_source: str = Field(..., description="Texte brut du document (sortie OCR)")


class DocumentOut(BaseModel):
    id: int
    entreprise_id: int
    type_doc: TypeDocument
    status: StatutDocument
    uploaded_at: dt.datetime

    class Config:
        from_attributes = True


class ExtractionOut(BaseModel):
    id: int
    document_id: int
    nom_entreprise: Optional[str]
    siren_extrait: Optional[str]
    date_emission: Optional[dt.datetime]
    date_expiration: Optional[dt.datetime]
    montant: Optional[float]
    confiance: Optional[float]

    class Config:
        from_attributes = True


class AnomalieOut(BaseModel):
    id: int
    entreprise_id: int
    document_id: Optional[int]
    type_anomalie: str
    description: str
    niveau_gravite: NiveauGravite
    resolue: bool
    created_at: dt.datetime

    class Config:
        from_attributes = True


class DossierConformite(BaseModel):
    """Vue synthetique du dossier d'une entreprise, utilisee par le dashboard."""
    entreprise: EntrepriseOut
    documents: list[DocumentOut]
    anomalies: list[AnomalieOut]
    conforme: bool
    pieces_manquantes: list[TypeDocument]
