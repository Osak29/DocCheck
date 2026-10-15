"""
Bloc 1 : Extraction & Structuration (IA).

Principe : le LLM ne fait AUCUNE deduction metier. On lui impose un schema
JSON strict (via tool use / structured output) et on lui interdit d'inventer
une valeur : un champ absent du document doit rester `null`.

Toute la logique de decision (expire ? coherent ? complet ?) vit dans
`rules_engine.py`, pas ici.
"""
import json
import logging

from anthropic import Anthropic

from app.config import settings
from app.schemas import ExtractionLLM

logger = logging.getLogger(__name__)

# Schema JSON envoye au LLM sous forme d'outil "force" : le modele DOIT
# repondre en remplissant cet outil, ce qui garantit un JSON valide.
EXTRACTION_TOOL = {
    "name": "enregistrer_extraction",
    "description": (
        "Enregistre les informations extraites du document administratif. "
        "Ne jamais inventer une valeur : si une information n'est pas "
        "explicitement presente dans le texte, renvoyer null pour ce champ."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "document_type": {
                "type": ["string", "null"],
                "enum": ["KBIS", "ATTESTATION_URSSAF", "ASSURANCE_DECENNALE",
                         "RC_PRO", "ATTESTATION_FISCALE", "AUTRE", None],
                "description": "Type de document identifie",
            },
            "nom_entreprise": {"type": ["string", "null"]},
            "siren": {"type": ["string", "null"], "description": "9 chiffres, sans espaces"},
            "date_emission": {"type": ["string", "null"], "description": "Format YYYY-MM-DD"},
            "date_expiration": {"type": ["string", "null"], "description": "Format YYYY-MM-DD"},
            "montant": {"type": ["number", "null"], "description": "Montant/plafond si present"},
            "confiance": {"type": "number", "description": "Confiance globale (0-1)"},
        },
        "required": ["confiance"],
    },
}

SYSTEM_PROMPT = (
    "Tu es un moteur d'extraction de donnees. Tu lis un document administratif "
    "francais (Kbis, attestation URSSAF, attestation d'assurance decennale, "
    "RC Pro, attestation fiscale...) et tu extrais UNIQUEMENT les informations "
    "explicitement presentes dans le texte, via l'outil fourni. "
    "Tu ne dois jamais calculer, deduire ou supposer une date, un statut de "
    "conformite ou une coherence : cela est fait ailleurs, par un moteur de "
    "regles deterministe. Ton seul role est la lecture fidele du document."
)


class ExtractionClient:
    """Fine couche autour de l'API Anthropic pour produire un `ExtractionLLM`
    a partir d'un texte de document (deja passe par OCR en amont, via ex.
    Docling / Unstructured / pytesseract)."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model
        self._client = Anthropic(api_key=self.api_key) if self.api_key else None

    def extract(self, texte_document: str) -> ExtractionLLM:
        if not self._client:
            raise RuntimeError(
                "ANTHROPIC_API_KEY manquante : configure-la dans .env pour "
                "activer l'extraction IA."
            )

        response = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "enregistrer_extraction"},
            messages=[
                {
                    "role": "user",
                    "content": f"Voici le texte du document a analyser :\n\n{texte_document}",
                }
            ],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "enregistrer_extraction":
                data = block.input
                logger.info("Extraction LLM brute: %s", json.dumps(data, ensure_ascii=False))
                return ExtractionLLM(**data)

        raise RuntimeError("Le LLM n'a pas renvoye de resultat structure exploitable.")


class MockExtractionClient(ExtractionClient):
    """Client de secours utilisable sans cle API (tests, demo, CI). Fait une
    extraction naive par mots-cles pour permettre de tester tout le pipeline
    (BDD, regles, API, dashboard) sans dependre d'Internet."""

    def __init__(self):
        pass

    def extract(self, texte_document: str) -> ExtractionLLM:
        import re

        siren_match = re.search(r"\b(\d{3}\s?\d{3}\s?\d{3})\b", texte_document)
        date_matches = re.findall(r"\b(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b", texte_document)

        def normalize_date(d):
            if not d:
                return None
            if "/" in d:
                j, m, a = d.split("/")
                return f"{a}-{m}-{j}"
            return d

        return ExtractionLLM(
            siren=siren_match.group(1).replace(" ", "") if siren_match else None,
            date_emission=normalize_date(date_matches[0]) if len(date_matches) > 0 else None,
            date_expiration=normalize_date(date_matches[-1]) if len(date_matches) > 1 else None,
            confiance=0.4,
        )


def get_extraction_client() -> ExtractionClient:
    """Factory : bascule automatiquement vers le mock si aucune cle API n'est
    configuree, pour que le projet tourne 'out of the box'."""
    if settings.anthropic_api_key:
        return ExtractionClient()
    logger.warning("Aucune ANTHROPIC_API_KEY configuree -> utilisation du MockExtractionClient.")
    return MockExtractionClient()
