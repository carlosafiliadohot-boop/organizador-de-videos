import os
import io
import re
import gc
import json
import math
import hmac
import time
import uuid
import base64
import shutil
import zipfile
import tempfile
import threading
import subprocess
import unicodedata
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Estúdio Pro Ultimate — Automação de Vídeos IA", page_icon="🎬", layout="wide")

@st.cache_resource
def get_render_semaphore():
    return threading.Semaphore(2)

@st.cache_resource
def get_ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

# ================= AUTENTICAÇÃO SAAS (SECRETS + SUPABASE AUTOMÁTICO) =================
def verify_supabase_subscriber(email, password):
    try:
        sb_url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
        sb_key = str(st.secrets.get("SUPABASE_KEY", "")).strip()
        if not sb_url or not sb_key:
            return False
        headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
        r = requests.get(
            f"{sb_url}/rest/v1/assinantes",
            headers=headers,
            params={"email": f"eq.{email}", "ativo": "eq.true", "select": "senha"},
            timeout=8
        )
        if r.status_code == 200 and r.json():
            db_pass = str(r.json()[0].get("senha", "")).strip()
            return bool(db_pass and hmac.compare_digest(password, db_pass))
    except Exception:
        pass
    return False

def check_saas_login():
    if st.session_state.get("authenticated", False):
        return

    admin_email, admin_pass = "", ""
    subscribers = {}
    has_supabase = False
    try:
        admin_email = str(st.secrets.get("ADMIN_EMAIL", "admin")).strip().lower()
        admin_pass = str(st.secrets.get("ADMIN_PASS", "")).strip()
        raw_subs = st.secrets.get("ASSINANTES", {})
        subscribers = {str(k).strip().lower(): str(v).strip() for k, v in dict(raw_subs).items()}
        has_supabase = bool(st.secrets.get("SUPABASE_URL", ""))
    except Exception:
        pass

    if not admin_pass and not subscribers and not has_supabase:
        st.warning("⚠️ Configure `ADMIN_EMAIL`, `ADMIN_PASS` e `[ASSINANTES]` em Manage app -> Settings -> Secrets!")
        st.stop()

    c1, c2, c3 = st.columns([1, 1.3, 1])
    with c2:
        st.markdown("## 🎬 Área de Membros — Estúdio Pro Ultimate")
        st.caption("Entre com o e-mail e a senha da sua assinatura ativa.")
        with st.form("saas_login_form"):
            u_email = st.text_input("📧 E-mail de acesso:", placeholder="seuemail@exemplo.com").strip().lower()
            u_pass = st.text_input("🔑 Senha:", type="password", placeholder="Sua senha")
            submit = st.form_submit_button("Acessar Estúdio", type="primary", use_container_width=True)

            if submit:
                p_clean = u_pass.strip()
                if admin_pass and hmac.compare_digest(u_email, admin_email) and hmac.compare_digest(p_clean, admin_pass):
                    st.session_state["authenticated"] = True
                    st.session_state["user_role"] = "admin"
                    st.session_state["user_email"] = u_email
                    st.rerun()
                elif (u_email in subscribers and hmac.compare_digest(p_clean, subscribers[u_email])) or verify_supabase_subscriber(u_email, p_clean):
                    st.session_state["authenticated"] = True
                    st.session_state["user_role"] = "subscriber"
                    st.session_state["user_email"] = u_email
                    st.rerun()
                else:
                    st.error("❌ E-mail ou senha inválidos (ou assinatura inativa).")
    st.stop()

check_saas_login()
# =====================================================================================

DEFAULT_CHAR_A = (
    "52-year-old Brazilian rural father, tanned skin, clean-shaven cheeks with thick dark-gray mustache, "
    "beige straw hat and solid navy-blue button-up shirt with rolled sleeves"
)
DEFAULT_CHAR_B = (
    "22-year-old Brazilian young woman, warm olive skin, shoulder-length dark brown curly hair, "
    "mustard-yellow ribbed t-shirt under a classic medium-blue denim jacket"
)

for k_def, v_def in {
    "saved_script": "",
    "auto_cast_dna": "",
    "seo_kit_output": "",
    "auto_duration_min": 1,
    "dna_char_a": DEFAULT_CHAR_A,
    "dna_char_b": DEFAULT_CHAR_B,
    "dna_single_char": "",
    "voice_char_a": "52-year-old Brazilian male baritone voice (105 Hz), calm Minas Gerais accent",
    "voice_char_b": "22-year-old Brazilian young female voice (210 Hz), natural expressive accent",
    "uploader_reset_id": 0
}.items():
    if k_def not in st.session_state:
        st.session_state[k_def] = v_def

LANGUAGES = {
    "🇧🇷 Português (Brasil)": {
        "sr_code": "pt-BR",
        "whisper_code": "pt",
        "name_en": "Brazilian Portuguese (pt-BR)",
        "end_keywords": [
            "grande abraco", "visitaria primeiro", "proximo video", "proximo dossie",
            "comente aqui", "ate a proxima", "qual dessas", "inscreva se",
            "ate o proximo video", "clique e compartilhe", "curta e compartilhe"
        ]
    },
    "🇪🇸 Espanhol (Latino/Neutro)": {
        "sr_code": "es-MX",
        "whisper_code": "es",
        "name_en": "Latin American Spanish (es-419)",
        "end_keywords": ["gran abrazo", "proximo video", "deja tu comentario", "hasta la proxima", "cual elegirias", "suscribete", "comparte"]
    },
    "🇺🇸 Inglês (EUA)": {
        "sr_code": "en-US",
        "whisper_code": "en",
        "name_en": "American English (en-US)",
        "end_keywords": ["next video", "leave a comment", "let us know in the comments", "thanks for watching", "see you next time", "subscribe", "like and share"]
    },
    "🇫🇷 Francês (França)": {
        "sr_code": "fr-FR",
        "whisper_code": "fr",
        "name_en": "French (fr-FR)",
        "end_keywords": ["prochaine video", "laissez un commentaire", "a bientot", "merci d avoir regarde", "abonnez vous"]
    },
    "🇮🇹 Italiano (Itália)": {
        "sr_code": "it-IT",
        "whisper_code": "it",
        "name_en": "Italian (it-IT)",
        "end_keywords": ["prossimo video", "lascia un commento", "a presto", "grazie per aver guardato", "iscriviti"]
    }
}

STYLE_PRESETS = {
    "Cinematográfico Realista 4K": (
        "Photorealistic 4K cinema footage, natural lighting, period-accurate wardrobe and setting, single continuous camera shot, zero text or signs on screen."
    ),
    "Cartoon 3D Pixar": (
        "3D Pixar-style animated feature film look, vibrant colors, soft global illumination, characters wearing strictly period-accurate clothing faithful to the story era (zero modern caps or anachronistic clothes), single continuous shot, zero text on screen."
    ),
    "Boneco Palito 2D": (
        "2D flat minimalist vector animation, consistent simple white stick figure characters dressed for the story context, clean background, single continuous shot, zero text on screen."
    ),
    "Personalizado (Definir abaixo)": ""
}

@st.cache_data
def build_chrome_extension_zip():
    manifest_str = """{
  "manifest_version": 3,
  "name": "Estúdio Pro — Auto-Enviador Google Flow v2.0",
  "version": "2.0",
  "description": "Dispara automaticamente cenas em linha única para o Google Flow preservando 100% o idioma do áudio.",
  "permissions": ["activeTab", "scripting", "storage"],
  "host_permissions": ["https://labs.google/*"],
  "content_scripts": [
    {
      "matches": ["https://labs.google/*"],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ]
}"""
    content_js_str = r"""(function () {
  if (document.getElementById("estudio-pro-panel")) return;
  let isRunning = false, stopRequested = false;
  const panel = document.createElement("div");
  panel.id = "estudio-pro-panel";
  panel.style.cssText = "position:fixed;bottom:20px;right:20px;width:340px;background:#111827;color:#f9fafb;border:1px solid #374151;border-radius:12px;padding:14px;z-index:999999;font-family:system-ui,sans-serif;box-shadow:0 12px 30px rgba(0,0,0,0.55);font-size:13px;";
  panel.innerHTML =
