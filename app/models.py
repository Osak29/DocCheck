"""
Modeles SQLAlchemy - schema de la base de donnees.

    entreprises  1---* documents  1---1 extractions
    entreprises  1---* anomalies

"""
import enum
import datetime as dt

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey,
    Text, Enum as SAEnum, JSON,
)
from sqlalchemy.orm import relationship

from app.database import Base


class TypeDocument(str, enum.Enum):
    KBIS = "KBIS"
    URSSAF = "ATTESTATION_URSSAF"
    ASSURANCE_DECENNALE = "ASSURANCE_DECENNALE"
    RC_PRO = "RC_PRO"
    ATTESTATION_FISCALE = "ATTESTATION_FISCALE"
    AUTRE = "AUTRE"


class StatutDocument(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"          # uploade, pas encore extrait
    VALIDE = "VALIDE"                  # extrait + conforme
    EXPIRE = "EXPIRE"
    ANOMALIE = "ANOMALIE"              # incoherence detectee (SIREN, etc.)
    A_RELANCER = "A_RELANCER"          # proche de l'expiration


class NiveauGravite(str, enum.Enum):
    INFO = "INFO"
    AVERTISSEMENT = "AVERTISSEMENT"
    BLOQUANT = "BLOQUANT"


class Entreprise(Base):
    __tablename__ = "entreprises"

    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String(255), nullable=False)
    siren = Column(String(9), nullable=False, index=True)
    email_contact = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    documents = relationship("Document", back_populates="entreprise", cascade="all, delete-orphan")
    anomalies = relationship("Anomalie", back_populates="entreprise", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    entreprise_id = Column(Integer, ForeignKey("entreprises.id"), nullable=False)
    type_doc = Column(SAEnum(TypeDocument), nullable=False)
    url_file = Column(String(500), nullable=True)       # chemin/S3 key du fichier source
    texte_source = Column(Text, nullable=True)           # texte brut post-OCR
    status = Column(SAEnum(StatutDocument), default=StatutDocument.EN_ATTENTE)
    uploaded_at = Column(DateTime, default=dt.datetime.utcnow)

    entreprise = relationship("Entreprise", back_populates="documents")
    extraction = relationship("Extraction", back_populates="document", uselist=False, cascade="all, delete-orphan")


class Extraction(Base):
    __tablename__ = "extractions"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, unique=True)

    nom_entreprise = Column(String(255), nullable=True)
    siren_extrait = Column(String(9), nullable=True)
    date_emission = Column(DateTime, nullable=True)
    date_expiration = Column(DateTime, nullable=True)
    montant = Column(Float, nullable=True)               # ex: plafond garantie RC/decennale
    confiance = Column(Float, nullable=True)              # 0-1, confiance de l'extraction LLM

    json_raw = Column(JSON, nullable=True)                # reponse structuree complete du LLM
    extracted_at = Column(DateTime, default=dt.datetime.utcnow)

    document = relationship("Document", back_populates="extraction")


class Anomalie(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, index=True)
    entreprise_id = Column(Integer, ForeignKey("entreprises.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)

    type_anomalie = Column(String(100), nullable=False)   # ex: SIREN_INCOHERENT, DOC_EXPIRE, DOC_MANQUANT
    description = Column(Text, nullable=False)
    niveau_gravite = Column(SAEnum(NiveauGravite), default=NiveauGravite.AVERTISSEMENT)
    resolue = Column(Boolean, default=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    entreprise = relationship("Entreprise", back_populates="anomalies")
