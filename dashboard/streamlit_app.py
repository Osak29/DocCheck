"""
Bloc 4ter : Dashboard Streamlit.

Consomme uniquement l'API FastAPI (aucun acces direct a la BDD depuis le
front) : upload d'un document, declenchement du traitement, et vue
synthetique des dossiers / anomalies.

Lancement : streamlit run dashboard/streamlit_app.py
"""
import io
import os
import sys

import pandas as pd
import requests
import streamlit as st
from pypdf import PdfReader

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="DocCheck", page_icon="📋", layout="wide")
st.title("📋 DocCheck — Audit & Controle Documentaire")
st.caption("Plateforme hybride Regles + IA de suivi de conformite documentaire (BTP)")


def api_get(path, **params):
    try:
        r = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        st.error(f"Erreur API ({path}) : {e}")
        return None


def api_post(path, json=None):
    try:
        r = requests.post(f"{API_BASE_URL}{path}", json=json, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        st.error(f"Erreur API ({path}) : {e}")
        return None


tab_dossiers, tab_upload, tab_anomalies = st.tabs(
    ["🏢 Dossiers entreprises", "📤 Nouveau document", "🚨 Anomalies"]
)

# ---------------------------------------------------------------------------
# Onglet Dossiers
# ---------------------------------------------------------------------------
with tab_dossiers:
    entreprises = api_get("/entreprises") or []
    if not entreprises:
        st.info("Aucune entreprise enregistree pour le moment. Cree-la dans l'onglet 'Nouveau document'.")
    else:
        noms = {f"{e['nom']} (SIREN {e['siren']})": e["id"] for e in entreprises}
        choix = st.selectbox("Choisir une entreprise", list(noms.keys()))
        entreprise_id = noms[choix]

        dossier = api_get(f"/entreprises/{entreprise_id}/dossier")
        if dossier:
            col1, col2, col3 = st.columns(3)
            col1.metric("Statut global", "✅ Conforme" if dossier["conforme"] else "⚠️ Non conforme")
            col2.metric("Documents", len(dossier["documents"]))
            col3.metric("Anomalies actives", len([a for a in dossier["anomalies"] if not a["resolue"]]))

            if dossier["pieces_manquantes"]:
                st.warning("Pieces manquantes : " + ", ".join(dossier["pieces_manquantes"]))

            st.subheader("Documents")
            if dossier["documents"]:
                df = pd.DataFrame(dossier["documents"])[["id", "type_doc", "status", "uploaded_at"]]
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.write("Aucun document.")

            st.subheader("Anomalies")
            if dossier["anomalies"]:
                dfa = pd.DataFrame(dossier["anomalies"])[
                    ["id", "type_anomalie", "niveau_gravite", "description", "resolue"]
                ]
                st.dataframe(dfa, use_container_width=True, hide_index=True)
            else:
                st.write("Aucune anomalie. 🎉")

# ---------------------------------------------------------------------------
# Onglet Upload
# ---------------------------------------------------------------------------
with tab_upload:
    st.subheader("1. Entreprise")
    with st.expander("Creer une nouvelle entreprise"):
        nom = st.text_input("Nom de l'entreprise")
        siren = st.text_input("SIREN (9 chiffres)")
        email = st.text_input("Email de contact")
        if st.button("Creer l'entreprise"):
            res = api_post("/entreprises", {"nom": nom, "siren": siren, "email_contact": email or None})
            if res:
                st.success(f"Entreprise creee (id={res['id']})")

    entreprises = api_get("/entreprises") or []
    if entreprises:
        noms = {f"{e['nom']} (SIREN {e['siren']})": e["id"] for e in entreprises}
        choix = st.selectbox("Entreprise concernee", list(noms.keys()), key="upload_ent")
        entreprise_id = noms[choix]

        st.subheader("2. Document")
        type_doc = st.selectbox(
            "Type de document",
            ["KBIS", "ATTESTATION_URSSAF", "ASSURANCE_DECENNALE", "RC_PRO", "ATTESTATION_FISCALE", "AUTRE"],
        )

        fichier_pdf = st.file_uploader("Importer un PDF (texte, pas un scan image)", type=["pdf"])
        texte_depuis_pdf = ""
        if fichier_pdf is not None:
            try:
                reader = PdfReader(io.BytesIO(fichier_pdf.read()))
                texte_depuis_pdf = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
                if texte_depuis_pdf:
                    st.success(f"Texte extrait du PDF ({len(reader.pages)} page(s)).")
                else:
                    st.warning(
                        "Aucun texte extrait : ce PDF est probablement un scan image. "
                        "Colle le texte manuellement ci-dessous, ou passe-le d'abord par un OCR."
                    )
            except Exception as e:
                st.error(f"Impossible de lire ce PDF : {e}")

        texte = st.text_area(
            "Texte du document (rempli automatiquement si PDF importe, sinon colle-le ici)",
            value=texte_depuis_pdf,
            height=200,
            placeholder="Ex : KBIS ... SIREN 123 456 789 ... Date d'emission 2026-01-15 ...",
        )

        if st.button("📤 Uploader puis traiter (extraction + regles)"):
            doc = api_post("/documents", {
                "entreprise_id": entreprise_id, "type_doc": type_doc, "texte_source": texte,
            })
            if doc:
                st.success(f"Document cree (id={doc['id']}), lancement du traitement...")
                traite = api_post(f"/documents/{doc['id']}/traiter")
                if traite:
                    st.success(f"Statut final : {traite['status']}")
    else:
        st.info("Cree d'abord une entreprise ci-dessus.")

# ---------------------------------------------------------------------------
# Onglet Anomalies
# ---------------------------------------------------------------------------
with tab_anomalies:
    st.subheader("Anomalies non resolues")
    anomalies = api_get("/anomalies", resolue=False) or []
    if anomalies:
        df = pd.DataFrame(anomalies)[
            ["id", "entreprise_id", "type_anomalie", "niveau_gravite", "description"]
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)

        id_a_resoudre = st.number_input("ID de l'anomalie a marquer resolue", min_value=0, step=1)
        if st.button("Marquer comme resolue") and id_a_resoudre:
            res = api_post(f"/anomalies/{int(id_a_resoudre)}/resoudre")
            if res:
                st.success("Anomalie resolue.")
                st.rerun()
    else:
        st.write("Aucune anomalie active. 🎉")