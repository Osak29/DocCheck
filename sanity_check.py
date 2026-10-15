"""
Verification rapide de bout-en-bout, sans dependre d'une cle API externe
(utilise le MockExtractionClient) : cree une entreprise, uploade 2
documents (un valide, un expire), lance le traitement, et affiche le
dossier de conformite resultant.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./sanity_check.db")

from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db

init_db()
client = TestClient(app)

# 1. Creer une entreprise
r = client.post("/entreprises", json={"nom": "BTP Dupont SARL", "siren": "123456789", "email_contact": "contact@btp-dupont.fr"})
assert r.status_code == 200, r.text
entreprise = r.json()
print("Entreprise creee:", entreprise)

# 2. Document valide (URSSAF, date future)
r = client.post("/documents", json={
    "entreprise_id": entreprise["id"],
    "type_doc": "ATTESTATION_URSSAF",
    "texte_source": "Attestation URSSAF - SIREN 123 456 789 - Date d'emission 15/01/2026 - Valable jusqu'au 31/12/2026",
})
assert r.status_code == 200, r.text
doc1 = r.json()
print("Document 1 cree:", doc1)

r = client.post(f"/documents/{doc1['id']}/traiter")
assert r.status_code == 200, r.text
print("Document 1 traite ->", r.json())

# 3. Document expire (assurance decennale, date passee) + SIREN incoherent
r = client.post("/documents", json={
    "entreprise_id": entreprise["id"],
    "type_doc": "ASSURANCE_DECENNALE",
    "texte_source": "Attestation assurance decennale - SIREN 987 654 321 - emis le 01/01/2020 - expire le 01/01/2021",
})
doc2 = r.json()
r = client.post(f"/documents/{doc2['id']}/traiter")
assert r.status_code == 200, r.text
print("Document 2 traite ->", r.json())

# 4. Dossier de conformite
r = client.get(f"/entreprises/{entreprise['id']}/dossier")
assert r.status_code == 200, r.text
dossier = r.json()
print("\n=== DOSSIER DE CONFORMITE ===")
print("Conforme:", dossier["conforme"])
print("Pieces manquantes:", dossier["pieces_manquantes"])
print("Anomalies:")
for a in dossier["anomalies"]:
    print(f"  - [{a['niveau_gravite']}] {a['type_anomalie']}: {a['description']}")

# 5. Anomalies globales
r = client.get("/anomalies")
print(f"\nTotal anomalies en base: {len(r.json())}")

print("\n✅ Sanity check termine avec succes.")
