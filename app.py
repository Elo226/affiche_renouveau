import streamlit as st
from datetime import date, time, datetime
import json
import os
# import hashlib # SUPPRIMÉ
import gspread  # NOUVEL IMPORT
import pandas as pd  # NOUVEL IMPORT

# --- Configuration et Initialisation ---

st.set_page_config(
    page_title="Gestionnaire d'Événements et Rappels",
    layout="wide"
)

# --- CONFIGURATION GOOGLE SHEETS (utilisant st.secrets) ---
# Liste des en-têtes de colonnes attendus dans votre Google Sheet (CRUCIAL)
COLUMN_HEADERS = [
    "type", "paroisse", "evenement_titre", "evenement_description",
    "date_debut", "date_fin", "date_evenement", "heure_evenement",
    "created_at"
]

try:
    SHEET_NAME = st.secrets["google_sheets"]["sheet_name"]
except KeyError:
    st.error(
        "Erreur de configuration: La clé 'sheet_name' est manquante. Vérifiez votre fichier .streamlit/secrets.toml.")
    st.stop()


# --- Configuration de l'Authentification SANS HACHAGE ---

# Ancien : HARDCODED_USERNAME = "Groupe Emmanuel"
# Ancien : HARDCODED_PASSWORD_HASH = hash_password("RCC123")
HARDCODED_USERNAME = "Groupe Emmanuel"
HARDCODED_PASSWORD = "RCC2025" # Mot de passe en CLAIR

# --- FONCTIONS DE CONNEXION GOOGLE SHEETS ---

@st.cache_resource(ttl=3600)  # Mise en cache de la connexion pour 1h
def get_gspread_client():
    """Initialise et retourne le client gspread en utilisant les secrets Streamlit."""
    try:
        secrets = st.secrets["gcp_service_account"]
        # Assure que la clé privée est correctement formatée pour gspread (gestion des \n)
        gcp_credentials = {k: v.replace('\\n', '\n') if k == 'private_key' else v for k, v in secrets.items()}

        gc = gspread.service_account_from_dict(gcp_credentials)
        return gc
    except KeyError:
        st.error(
            "Erreur de configuration: La section '[gcp_service_account]' n'est pas trouvée dans .streamlit/secrets.toml.")
        return None
    except Exception as e:
        st.error(f"Erreur d'authentification GSpread: {e}")
        return None


gc = get_gspread_client()


@st.cache_resource(ttl=300)  # Mise en cache de la feuille pour 5 min
def get_worksheet():
    if not gc:
        return None
    try:
        sh = gc.open(SHEET_NAME)
        worksheet = sh.worksheet("annonce") # Ouvre la première feuille de calcul
        return worksheet
    except Exception as e:
        st.error(
            f"Erreur lors de l'ouverture de la Google Sheet '{SHEET_NAME}'. Avez-vous partagé la feuille avec l'email du compte de service? Détail: {e}")
        return None


# --- FONCTION DE CHARGEMENT (Remplacement de load_annonces JSON) ---

def load_annonces():
    """Charge la liste des annonces depuis Google Sheets."""
    ws = get_worksheet()
    if not ws:
        return []

    try:
        list_of_dicts = ws.get_all_records(head=1, empty2zero=False)
        return list_of_dicts

    except Exception as e:
        st.error(f"Erreur lors de la lecture des annonces depuis Google Sheets. Détail: {e}")
        return []


# Initialisation de la session state
if 'annonces' not in st.session_state:
    st.session_state.annonces = load_annonces()

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False


# --- Fonctions de Traitement (Mise à jour pour l'écriture GSpread) ---

def _add_annonce_to_list(new_annonce, paroisse, evenement_titre):
    """Fonction interne pour ajouter une annonce en session et dans Google Sheets (APPEND)."""

    # 1. Mise à jour de la session state
    st.session_state.annonces.append(new_annonce)

    # 2. Sauvegarde dans Google Sheets (APPEND NOUVELLE LIGNE)
    ws = get_worksheet()
    if not ws:
        st.warning(
            "Annonce ajoutée localement, mais la connexion à Google Sheets a échoué. Elle sera perdue si vous quittez l'application.")
        return

    try:
        # Construit une liste de valeurs dans l'ordre des entêtes
        row_data = [new_annonce.get(header, "") for header in COLUMN_HEADERS]

        # Ajout de la ligne à la feuille
        ws.append_row(row_data, value_input_option='USER_ENTERED')

    except Exception as e:
        st.error(f"Erreur critique lors de l'ajout de l'annonce dans Google Sheets: {e}")


def add_annonce_periode(paroisse, evenement_titre, evenement_description, date_debut, date_fin, heure_evenement):
    """Ajoute une annonce de type 'periode' (multi-jours)."""
    new_annonce = {
        "type": "periode",
        "paroisse": paroisse,
        "evenement_titre": evenement_titre,
        "evenement_description": evenement_description,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "heure_evenement": heure_evenement,
        "created_at": date.today().isoformat()
    }
    _add_annonce_to_list(new_annonce, paroisse, evenement_titre)
    st.success(
        f"Événement période **'{evenement_titre}'** pour **'{paroisse}'** enregistré du {date_debut} au {date_fin}.")


def add_annonce_ponctuel(paroisse, evenement_titre, evenement_description, date_evenement, heure_evenement):
    """Ajoute une annonce de type 'ponctuel' (date unique)."""
    new_annonce = {
        "type": "ponctuel",
        "paroisse": paroisse,
        "evenement_titre": evenement_titre,
        "evenement_description": evenement_description,
        "date_evenement": date_evenement,
        "heure_evenement": heure_evenement,
        "created_at": date.today().isoformat()
    }
    _add_annonce_to_list(new_annonce, paroisse, evenement_titre)
    st.success(
        f"Événement ponctuel **'{evenement_titre}'** pour **'{paroisse}'** enregistré pour le {date_evenement} à {heure_evenement}.")


def filter_and_cleanup_annonces():
    """
    Filtre les annonces actives et met à jour la session state UNIQUEMENT.
    Ne touche pas à la Google Sheet.
    """
    today_iso = date.today().isoformat()
    now_time = datetime.now().strftime("%H:%M")

    active_annonces = []
    expired_count = 0

    for annonce in st.session_state.annonces:
        annonce_type = annonce.get('type', 'ponctuel')

        is_expired = False

        if annonce_type == 'periode':
            date_fin = annonce.get('date_fin')
            if not date_fin or date_fin < today_iso:
                is_expired = True

        elif annonce_type == 'ponctuel':
            date_evt = annonce.get('date_evenement')
            heure_evt = annonce.get('heure_evenement', '00:00')

            if not date_evt:
                is_expired = True
            elif date_evt < today_iso:
                is_expired = True
            elif date_evt == today_iso and heure_evt < now_time:
                is_expired = True

        if is_expired:
            expired_count += 1
        else:
            active_annonces.append(annonce)

    # Mise à jour de la session state (nettoyage local/affiché)
    if expired_count > 0:
        st.session_state.annonces = active_annonces
        # L'appel à save_annonces (sauvegarde distante) est bien retiré.

    return active_annonces, expired_count


# --- Fonction de Connexion (CORRIGÉE) ---
def check_login(username, password):
    """Vérifie les identifiants de l'utilisateur."""
    if username == HARDCODED_USERNAME and password == HARDCODED_PASSWORD:
        st.session_state.logged_in = True
    else:
        st.error("Nom d'utilisateur ou mot de passe incorrect.")
        st.error(username,password)


# Fonction de déconnexion
def logout():
    """Déconnecte l'utilisateur et recharge les données depuis Google Sheets."""
    st.session_state.logged_in = False
    # On recharge les données au moment de la déconnexion pour s'assurer que la prochaine session est à jour
    st.session_state.annonces = load_annonces()


def show_login_page():
    """Affiche la page de connexion, alignée au centre."""

    col_spacer_left, col_center, col_spacer_right = st.columns([1, 1, 1])

    with col_center:
        st.markdown(
            """
            <h1 style='text-align: center; color: #1f77b4;'>
                🔒 Login
            </h1>
            <p style='text-align: center;'>
                Veuillez entrer vos identifiants.
            </p>
            """,
            unsafe_allow_html=True
        )

        with st.container(border=True):
            st.subheader("Authentification")
            with st.form("login_form"):
                username = st.text_input("Nom d'utilisateur", key="username_input")
                password = st.text_input("Mot de passe", type="password", key="password_input")
                submitted = st.form_submit_button("Se Connecter")

                if submitted:
                    check_login(username, password)


# --- APPLICATION PRINCIPALE (Logique de Flux) ---

if not st.session_state.logged_in:
    show_login_page()
else:
    # --- EN-TÊTE PRINCIPAL (sans Sidebar) ---
    col_title, col_status, col_logout = st.columns([4, 2, 1])

    with col_title:
        st.markdown(
            """
            <h3 style='margin-top: 0; padding-top: 0;'>
                🗓️ Gestionnaire d'Événements et Rappels
            </h3>
            """,
            unsafe_allow_html=True
        )

    with col_status:
        st.markdown(f"**Connecté :** `{HARDCODED_USERNAME}`", unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

    with col_logout:
        st.button("Déconnexion", on_click=logout, key="main_logout_button")

    st.markdown("---")

    # Création des onglets
    tab_add_period, tab_add_single, tab_reminders = st.tabs(
        ["➕ Event périodique ", "➕ Event ponctuel", "🔔 Rappels"])

    # --- Onglet 1: Enregistrement Événement Période (Multi-Jours) ---
    with tab_add_period:
        st.markdown("<h4 style='font-size: 1.5rem; margin-top: 0;'>Ajouter un nouvel événement sur une période</h4>",
                    unsafe_allow_html=True)

        with st.form("add_event_period_form", clear_on_submit=True):

            paroisse_input_period = st.text_input(
                "1. Nom de la Paroisse",
                placeholder="Ex: Paroisse Saint-Pierre",
                key="paroisse_period"
            )

            evenement_titre_input_period = st.text_input(
                "2. Titre de l'Événement",
                placeholder="Ex: Campagne d'évangélisation, Fête paroissiale",
                key="titre_period"
            )

            evenement_description_input_period = st.text_area(
                "3. Description de l'Événement",
                placeholder="Ex: Campagne de 10 jours,...",
                key="desc_period"
            )

            col_date_debut, col_date_fin = st.columns(2)

            with col_date_debut:
                date_debut_input = st.date_input(
                    "4. Date de Début",
                    min_value=date.today(),
                    value=date.today(),
                    key="date_debut"
                )

            with col_date_fin:
                min_date_fin = date_debut_input if date_debut_input else date.today()
                date_fin_input = st.date_input(
                    "5. Date de Fin",
                    min_value=min_date_fin,
                    value=min_date_fin,
                    key="date_fin"
                )

            heure_evenement_input_period = st.time_input(
                "6. Heure de l'Événement",
                value=time(10, 0),
                key="heure_period"
            )

            submitted_period = st.form_submit_button("Enregistrer")

            if submitted_period:
                if date_debut_input > date_fin_input:
                    st.error("La date de fin ne peut pas être antérieure à la date de début.")
                elif paroisse_input_period and evenement_titre_input_period and evenement_description_input_period:
                    add_annonce_periode(
                        paroisse=paroisse_input_period,
                        evenement_titre=evenement_titre_input_period,
                        evenement_description=evenement_description_input_period,
                        date_debut=date_debut_input.isoformat(),
                        date_fin=date_fin_input.isoformat(),
                        heure_evenement=heure_evenement_input_period.strftime("%H:%M")
                    )
                else:
                    st.error("Veuillez remplir tous les champs obligatoires (Paroisse, Titre et Description).")

    # --- Onglet 2: Enregistrement Événement Ponctuel (Date Unique) ---
    with tab_add_single:
        st.markdown("<h4 style='font-size: 1.5rem; margin-top: 0;'>Ajouter un nouvel événement </h4>",
                    unsafe_allow_html=True)

        with st.form("add_event_single_form", clear_on_submit=True):
            paroisse_input_single = st.text_input(
                "1. Nom de la Paroisse",
                placeholder="Ex: Paroisse Saint-Pierre",
                key="paroisse_single"
            )

            evenement_titre_input_single = st.text_input(  # LIGNE CORRIGÉE
                "2. Titre de l'Événement",
                placeholder="Ex: Messe dominicale, Réunion du conseil",
                key="titre_single"
            )

            evenement_description_input_single = st.text_area(
                "3. Description de l'Événement",
                placeholder="Ex: Messe spéciale pour la fête de Pâques...",
                key="desc_single"
            )

            col_date_single, col_heure_single = st.columns(2)

            with col_date_single:
                date_evenement_input_single = st.date_input(
                    "4. Date de l'Événement",
                    min_value=date.today(),
                    value=date.today(),
                    key="date_single"
                )

            with col_heure_single:
                heure_evenement_input_single = st.time_input(
                    "5. Heure de l'Événement",
                    value=time(10, 0),
                    key="heure_single"
                )

            submitted_single = st.form_submit_button("Enregistrer")

            if submitted_single:
                if paroisse_input_single and evenement_titre_input_single and evenement_description_input_single:
                    add_annonce_ponctuel(
                        paroisse=paroisse_input_single,
                        evenement_titre=evenement_titre_input_single,
                        evenement_description=evenement_description_input_single,
                        date_evenement=date_evenement_input_single.isoformat(),
                        heure_evenement=heure_evenement_input_single.strftime("%H:%M")
                    )
                else:
                    st.error("Veuillez remplir tous les champs obligatoires (Paroisse, Titre et Description).")

    # --- Onglet 3: Rappels Actifs ---
    with tab_reminders:
        st.markdown("<h4 style='font-size: 1.5rem; margin-top: 0;'>🔔 Vos Rappels d'Événements Actifs</h4>",
                    unsafe_allow_html=True)
        st.write(f"Date du jour utilisée pour le filtre : **{date.today().strftime('%d/%m/%Y')}**")

        # 1. Filtrage et Nettoyage
        active_annonces, expired_count = filter_and_cleanup_annonces()

        if expired_count > 0:
            st.info(
                f"🗑️ **{expired_count}** événement(s) passé(s) ont été automatiquement nettoyé(s) de votre vue locale. Ces entrées existent toujours dans Google Sheets.")

        # 2. Affichage
        if not active_annonces:
            st.success("🎉 Aucun événement actif trouvé (en cours ou à venir).")
        else:
            def sort_key(annonce):
                if annonce.get('type') == 'periode':
                    # Utilise la date de début pour le tri
                    return annonce.get('date_debut', date.today().isoformat())
                    # Utilise la date de l'événement pour le tri
                return annonce.get('date_evenement', date.today().isoformat())


            active_annonces.sort(key=sort_key)

            st.subheader(f"Total des événements actifs : {len(active_annonces)}")

            for annonce in active_annonces:

                paroisse_name = annonce.get('paroisse', 'Paroisse Inconnue')
                titre = annonce.get('evenement_titre', 'Titre manquant')
                description = annonce.get('evenement_description', 'Pas de description')
                heure_evt = annonce.get('heure_evenement', 'Non spécifiée')

                annonce_type = annonce.get('type', 'ponctuel')
                today_date = date.today()

                status_text = "Statut indéterminé"
                alert_color = 'gray'
                period_caption = ""

                try:
                    if annonce_type == 'periode':
                        date_debut = date.fromisoformat(annonce.get('date_debut'))
                        date_fin = date.fromisoformat(annonce.get('date_fin'))

                        if today_date >= date_debut and today_date <= date_fin:
                            days_remaining = (date_fin - today_date).days
                            if days_remaining == 0:
                                status_text = f"🔥 **DERNIER JOUR AUJOURD'HUI !** (jusqu'à {heure_evt})"
                                alert_color = 'red'
                            elif days_remaining <= 3:
                                status_text = f"🚨 **EN COURS :** Termine dans {days_remaining} jour(s)"
                                alert_color = 'red'
                            else:
                                status_text = f"▶️ **EN COURS** (Termine le {date_fin.strftime('%d/%m/%Y')})"
                                alert_color = 'green'

                        elif today_date < date_debut:
                            days_to_start = (date_debut - today_date).days
                            if days_to_start == 1:
                                status_text = f"🚨 **DEMAIN :** Commence !"
                                alert_color = 'red'
                            elif days_to_start <= 7:
                                status_text = f"⚠️ Bientôt : Commence dans {days_to_start} jours"
                                alert_color = 'orange'
                            else:
                                status_text = f"📅 Prévu : Commence dans {days_to_start} jours"
                                alert_color = 'blue'

                        period_caption = f"Période : Du **{date_debut.strftime('%d/%m/%Y')}** au **{date_fin.strftime('%d/%m/%Y')}** à partir de **{heure_evt}**"

                    elif annonce_type == 'ponctuel':
                        date_evt = date.fromisoformat(annonce.get('date_evenement'))
                        days_to_start = (date_evt - today_date).days

                        if days_to_start == 0:
                            status_text = f"🔥 **AUJOURD'HUI !** à **{heure_evt}**"
                            alert_color = 'red'
                        elif days_to_start == 1:
                            status_text = f"🚨 **DEMAIN !** à **{heure_evt}**"
                            alert_color = 'red'
                        elif days_to_start <= 7:
                            status_text = f"⚠️ Bientôt : Dans {days_to_start} jours"
                            alert_color = 'orange'
                        else:
                            status_text = f"📅 Prévu : Dans {days_to_start} jours"
                            alert_color = 'blue'

                        period_caption = f"Date : **{date_evt.strftime('%d/%m/%Y')}** à **{heure_evt}**"


                except (TypeError, ValueError, KeyError):
                    status_text = f"Date(s) invalide(s) (Type: {annonce_type})"
                    alert_color = 'gray'
                    period_caption = "Erreur de données"

                with st.container():
                    st.markdown(f"**Paroisse :** {paroisse_name}")
                    st.markdown(f"**Titre :** {titre}")
                    st.markdown(f"**Description :** {description}")
                    st.caption(period_caption)

                    st.markdown(
                        f'<div style="font-size: 1.0em; padding-top: 5px; font-weight: bold; color: {alert_color};"> {status_text}</div>',
                        unsafe_allow_html=True)

                    st.markdown("--- ")
