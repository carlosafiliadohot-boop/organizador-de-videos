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
DEFAULT_VOICE_A = "adult male baritone voice (110 Hz), natural expressive delivery"
DEFAULT_VOICE_B = "young adult female voice (205 Hz), clear natural delivery"

for k_def, v_def in {
    "saved_script": "",
    "auto_cast_dna": "",
    "seo_kit_output": "",
    "auto_duration_min": 1,
    "dna_char_a": DEFAULT_CHAR_A,
    "dna_char_b": DEFAULT_CHAR_B,
    "dna_single_char": "",
    "voice_char_a": DEFAULT_VOICE_A,
    "voice_char_b": DEFAULT_VOICE_B,
    "uploader_reset_id": 0,
    "custom_audio_1to1_lock": False,
    "_pending_cast_sync": {}
}.items():
    if k_def not in st.session_state:
        st.session_state[k_def] = v_def

if st.session_state.get("_pending_cast_sync"):
    for _pk, _pv in st.session_state["_pending_cast_sync"].items():
        st.session_state[_pk] = _pv
    st.session_state["_pending_cast_sync"] = {}

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
        "Photorealistic 4K cinema B-roll footage, natural cinematic lighting, strictly authentic geography and period-accurate wardrobe, single continuous camera shot, zero text, zero signs, zero TV presenters on screen."
    ),
    "Cartoon 3D Pixar": (
        "High-end 3D stylized animated feature film look, vibrant colors, soft global illumination, fictional animated characters wearing strictly period-accurate clothing faithful to the story era (zero modern caps or anachronistic clothes), single continuous shot, zero text on screen."
    ),
    "Boneco Palito 2D": (
        "2D flat minimalist vector animation, consistent simple white stick figure characters dressed for the story context, clean background, single continuous shot, zero text on screen."
    ),
    "Personalizado (Definir abaixo)": ""
}

@st.cache_data
def build_chrome_extension_zip():
    manifest_dict = {
        "manifest_version": 3,
        "name": "Estudio Pro — Auto-Enviador Google Flow v2.0",
        "version": "2.0",
        "description": "Dispara automaticamente cenas em linha unica para o Google Flow preservando 100% o idioma do audio.",
        "permissions": ["activeTab", "scripting", "storage"],
        "host_permissions": ["https://labs.google/*"],
        "content_scripts": [{"matches": ["https://labs.google/*"], "js": ["content.js"], "run_at": "document_idle"}]
    }
    js_lines = [
        '(function () {',
        '  if (document.getElementById("estudio-pro-panel")) return;',
        '  let isRunning = false, stopRequested = false;',
        '  const panel = document.createElement("div");',
        '  panel.id = "estudio-pro-panel";',
        '  panel.style.cssText = "position:fixed;bottom:20px;right:20px;width:340px;background:#111827;color:#f9fafb;border:1px solid #374151;border-radius:12px;padding:14px;z-index:999999;font-family:system-ui,sans-serif;box-shadow:0 12px 30px rgba(0,0,0,0.55);font-size:13px;";',
        '  panel.innerHTML = \'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><strong style="font-size:14px;color:#34d399;">Estudio Pro — Auto Flow v2.0</strong><button id="ep-min-btn" style="background:none;border:none;color:#9ca3af;cursor:pointer;font-size:16px;">—</button></div><div id="ep-body"><div style="margin-bottom:6px;color:#d1d5db;font-size:12px;">Cole abaixo o conteudo de <b>Prompts_Flow.txt</b>:</div><textarea id="ep-prompts" rows="5" placeholder="=== CENA 001 ===..." style="width:100%;box-sizing:border-box;background:#1f2937;color:#fff;border:1px solid #4b5563;border-radius:8px;padding:8px;font-size:12px;"></textarea><div style="display:flex;justify-content:space-between;align-items:center;margin:8px 0;"><label style="font-size:12px;color:#d1d5db;">Pausa entre cenas (seg):</label><input id="ep-delay" type="number" min="6" max="120" value="16" style="width:60px;background:#1f2937;color:#fff;border:1px solid #4b5563;border-radius:6px;padding:4px;text-align:center;"/></div><div style="display:flex;gap:8px;margin-top:8px;"><button id="ep-start" style="flex:1;background:#059669;color:#fff;border:none;border-radius:8px;padding:9px;font-weight:600;cursor:pointer;">Iniciar Fila v2.0</button><button id="ep-stop" style="background:#dc2626;color:#fff;border:none;border-radius:8px;padding:9px 12px;font-weight:600;cursor:pointer;display:none;">Parar</button></div><div id="ep-status" style="margin-top:8px;font-size:12px;color:#93c5fd;min-height:18px;">Pronto (Modo Linha Unica).</div></div>\';',
        '  document.body.appendChild(panel);',
        '  const bodyDiv = document.getElementById("ep-body");',
        '  document.getElementById("ep-min-btn").onclick = () => { bodyDiv.style.display = bodyDiv.style.display === "none" ? "block" : "none"; };',
        '  function parseScenes(raw) {',
        '    if (!raw || !raw.trim()) return [];',
        '    const p = raw.split(/===\\s*CENA\\s*\\d+\\s*===/i).map(s => s.replace(/[\\r\\n]+/g, " ").replace(/\\s+/g, " ").trim()).filter(Boolean);',
        '    return p.length > 0 ? p : [raw.replace(/[\\r\\n]+/g, " ").replace(/\\s+/g, " ").trim()];',
        '  }',
        '  function findFlowInput() {',
        '    const els = [...document.querySelectorAll("textarea"), ...document.querySelectorAll(\'[contenteditable="true"]\'), ...document.querySelectorAll(\'[role="textbox"]\')];',
        '    for (const el of els) {',
        '      if (el.id === "ep-prompts") continue;',
        '      const r = el.getBoundingClientRect();',
        '      if (r.width > 160 && r.height > 24) return el;',
        '    }',
        '    return null;',
        '  }',
        '  function setSingleLineText(el, cleanText) {',
        '    el.focus();',
        '    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {',
        '      const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;',
        '      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;',
        '      if (setter) setter.call(el, ""); else el.value = "";',
        '      el.dispatchEvent(new Event("input", { bubbles: true }));',
        '      if (setter) setter.call(el, cleanText); else el.value = cleanText;',
        '      el.dispatchEvent(new Event("input", { bubbles: true }));',
        '      el.dispatchEvent(new Event("change", { bubbles: true }));',
        '    } else {',
        '      document.execCommand("selectAll", false, null);',
        '      document.execCommand("delete", false, null);',
        '      document.execCommand("insertText", false, cleanText);',
        '      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: cleanText }));',
        '    }',
        '  }',
        '  function triggerSubmit(inputEl) {',
        '    const btn = [...document.querySelectorAll("button")].find(b => {',
        '      if (b.id.startsWith("ep-") || b.disabled) return false;',
        '      const lb = ((b.innerText || "") + " " + (b.getAttribute("aria-label") || "") + " " + (b.textContent || "")).toLowerCase();',
        '      return lb.includes("generate") || lb.includes("gerar") || lb.includes("create") || lb.includes("criar") || lb.includes("arrow_upward") || b.getAttribute("type") === "submit";',
        '    });',
        '    if (btn) { btn.click(); return; }',
        '    inputEl.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));',
        '  }',
        '  const sleep = ms => new Promise(r => setTimeout(r, ms));',
        '  document.getElementById("ep-stop").onclick = () => { stopRequested = true; };',
        '  document.getElementById("ep-start").onclick = async () => {',
        '    if (isRunning) return;',
        '    const scenes = parseScenes(document.getElementById("ep-prompts").value);',
        '    const delaySec = Math.max(6, parseInt(document.getElementById("ep-delay").value || "16", 10));',
        '    const statusEl = document.getElementById("ep-status");',
        '    if (!scenes.length) { statusEl.innerText = "Cole os prompts primeiro!"; return; }',
        '    if (!findFlowInput()) { statusEl.innerText = "Abra um projeto do Flow onde aparece a caixa de prompt!"; return; }',
        '    isRunning = true; stopRequested = false;',
        '    document.getElementById("ep-start").style.display = "none";',
        '    document.getElementById("ep-stop").style.display = "inline-block";',
        '    for (let i = 0; i < scenes.length; i++) {',
        '      if (stopRequested) break;',
        '      const box = findFlowInput();',
        '      if (!box) { await sleep(4000); i--; continue; }',
        '      statusEl.innerText = "Preenchendo cena " + (i + 1) + "/" + scenes.length + "...";',
        '      setSingleLineText(box, scenes[i]);',
        '      await sleep(1400);',
        '      triggerSubmit(box);',
        '      if (i < scenes.length - 1 && !stopRequested) {',
        '        for (let s = delaySec; s > 0; s--) {',
        '          if (stopRequested) break;',
        '          statusEl.innerText = "Cena " + (i + 1) + "/" + scenes.length + " enviada! Proxima em " + s + "s...";',
        '          await sleep(1000);',
        '        }',
        '      }',
        '    }',
        '    isRunning = false;',
        '    document.getElementById("ep-start").style.display = "inline-block";',
        '    document.getElementById("ep-stop").style.display = "none";',
        '    statusEl.innerText = stopRequested ? "Fila pausada." : "Todas as " + scenes.length + " cenas enviadas!";',
        '  };',
        '})();'
    ]
    readme_str = (
        "COMO INSTALAR A EXTENSAO VIP v2.0 NO CHROME:\n"
        "1. Extraia este .ZIP numa pasta no seu computador.\n"
        "2. Abra chrome://extensions, ative o 'Modo do desenvolvedor' no topo direito.\n"
        "3. Clique em 'Carregar sem compactacao' e selecione a pasta extraida.\n"
        "4. No Google Flow: use Veo 3 (com audio ligado), 1 video por prompt e desative a varinha de reescrever prompt."
    )
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Extensao_Estudio_Pro_Flow_v2/manifest.json", json.dumps(manifest_dict, indent=2))
        zf.writestr("Extensao_Estudio_Pro_Flow_v2/content.js", "\n".join(js_lines))
        zf.writestr("Extensao_Estudio_Pro_Flow_v2/COMO_INSTALAR.txt", readme_str)
    return mem_zip.getvalue()

def sanitize_visual_for_veo_safety(vis_en, is_narration_broll=False):
    if not vis_en:
        return ""
    s = vis_en
    s = re.sub(r'\bPixar[-\s]*style\b', '3D stylized animated', s, flags=re.IGNORECASE)
    s = re.sub(r'\bDisney\b', 'animated', s, flags=re.IGNORECASE)
    s = re.sub(r'\b(?:dead|corpse|bloody|bleeding|kills|killing)\b', 'defeated', s, flags=re.IGNORECASE)
    s = re.sub(r'\blies motionless\b', 'kneels defeated on the ground', s, flags=re.IGNORECASE)
    if is_narration_broll:
        # Remove neve europeia, apresentadores de TV e placas de texto em documentarios brasileiros
        s = re.sub(r'\b(?:snow|snowy|snowfall|blizzard|icy|freezing winter)\b', 'misty highland morning', s, flags=re.IGNORECASE)
        s = re.sub(r'\b(?:TV presenter|news anchor|host speaking|youtuber|pointing at map|thumbs up|subscribe button)\b', 'cinematic aerial cityscape', s, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', s).strip()

def fix_pronunciation(text, lang_label):
    if not text:
        return ""
    t = text.strip()
    if "Português" in lang_label:
        known_acronyms = {"IBGE", "UFJF", "UFU", "UFMG", "UFV", "UFSJ", "IDH", "PIB", "ONU", "EUA", "SUS", "CPF", "CNPJ"}
        def _decap(m):
            w = m.group(0)
            return w if w in known_acronyms else w.capitalize()
        t = re.sub(r'\b[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]{4,}\b', _decap, t)

        pt_names = {
            r'\bGoliath\b': 'Golias', r'\bDavid\b': 'Davi', r'\bSolomon\b': 'Salomão',
            r'\bMoses\b': 'Moisés', r'\bNoah\b': 'Noé', r'\bAbraham\b': 'Abraão',
            r'\bIsaac\b': 'Isaque', r'\bJacob\b': 'Jacó', r'\bJoseph\b': 'José',
            r'\bJoshua\b': 'Josué', r'\bElijah\b': 'Elias', r'\bElisha\b': 'Eliseu',
            r'\bJonah\b': 'Jonas', r'\bSamson\b': 'Sansão', r'\bElah\b': 'Elá',
            r'\bBethlehem\b': 'Belém', r'\bJerusalem\b': 'Jerusalém',
            r'\bPhilistines\b': 'filisteus', r'\bPhilistine\b': 'filisteu', r'\bIsraelites\b': 'israelitas'
        }
        for pat, rep in pt_names.items():
            t = re.sub(pat, rep, t, flags=re.IGNORECASE if pat == r'\bElah\b' else 0)

        t = re.sub(r'\binscreva[-\s]*on[-\s]*se\b', 'inscreva-se', t, flags=re.IGNORECASE)
        t = re.sub(r'\bEUA\b', 'Estados Unidos', t)
        t = re.sub(r'\bONU\b', 'Organização das Nações Unidas', t)
        t = re.sub(r'\bIBGE\b', 'I B G E', t)
        t = re.sub(r'\bUFJF\b', 'U F J F', t)
        t = re.sub(r'\bUFU\b', 'U F U', t)
        t = re.sub(r'\bUFMG\b', 'U F M G', t)
        t = re.sub(r'\bUFV\b', 'U F V', t)
        t = re.sub(r'\bUFSJ\b', 'U F S J', t)
        t = re.sub(r'\bUNIFEI\b', 'Unifei', t)
        t = re.sub(r'\bIDH\b', 'I D H', t)
        t = re.sub(r'\bPIB\b', 'P I B', t)
        t = re.sub(r'\bBH\b', 'Belo Horizonte', t)
        t = re.sub(r'\bJF\b', 'Juiz de Fora', t)
        t = re.sub(r'\bMG\b', 'Minas Gerais', t)
        t = re.sub(r'\bSP\b', 'São Paulo', t)
        t = re.sub(r'\bRJ\b', 'Rio de Janeiro', t)
        t = re.sub(r'\bBR[-\s]*040\b', 'B R zero quarenta', t, flags=re.IGNORECASE)
        t = re.sub(r'\bBR[-\s]*(\d+)\b', r'B R \1', t, flags=re.IGNORECASE)
        t = re.sub(r'R\$\s*(\d+)', r'\1 reais', t)
        t = re.sub(r'US\$\s*(\d+)', r'\1 dólares', t)
        t = re.sub(r'(\d+)\s*kg\b', r'\1 quilos', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*km/h\b', r'\1 quilômetros por hora', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*km\b', r'\1 quilômetros', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*m²\b', r'\1 metros quadrados', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*cm\b', r'\1 centímetros', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*%', r'\1 por cento', t)
    elif "Espanhol" in lang_label:
        t = re.sub(r'\bGoliath\b', 'Goliat', t)
        t = re.sub(r'\bEE\.?\s*UU\.?\b', 'Estados Unidos', t)
        t = re.sub(r'(\d+)\s*kg\b', r'\1 kilos', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*km\b', r'\1 kilómetros', t, flags=re.IGNORECASE)
    elif "Inglês" in lang_label:
        t = re.sub(r'(\d+)\s*kg\b', r'\1 kilograms', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*km\b', r'\1 kilometers', t, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', t).strip()

def get_compact_voice_profile(gender_choice, custom_voice_desc=""):
    extra = f", {custom_voice_desc.strip()}" if custom_voice_desc.strip() else ""
    if "Masculina" in gender_choice:
        return (
            f"MANDATORY CONTINUOUS VOICEOVER by the EXACT SAME adult male studio narrator "
            f"(deep chest-resonant baritone 115 Hz, warm studio mic{extra}; ZERO silence, ZERO extra improvised words, "
            f"NEVER use female or child voices)"
        )
    return (
        f"MANDATORY CONTINUOUS VOICEOVER by the EXACT SAME adult female studio narrator "
        f"(smooth mezzo-soprano 195 Hz, warm studio mic{extra}; ZERO silence, ZERO extra improvised words, "
        f"NEVER use male or child voices)"
    )

def clean_markdown(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL).strip()
    txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt)
    return re.sub(r"\n?```$", "", txt).strip()

def get_available_groq_models(clean_key, vision_only=False):
    headers_groq = {"Authorization": f"Bearer {clean_key}"}
    try:
        r_m = requests.get("https://api.groq.com/openai/v1/models", headers=headers_groq, timeout=15)
        if r_m.status_code == 200:
            raw_ids = [m["id"] for m in r_m.json().get("data", []) if "id" in m]
            skip_words = ("whisper", "guard", "tts", "playai", "orpheus", "embed", "safeguard", "allam")
            chat_models = [mid for mid in raw_ids if not any(sw in mid.lower() for sw in skip_words)]
            if vision_only:
                vis_models = [mid for mid in chat_models if any(vk in mid.lower() for vk in ("llama-4", "scout", "maverick", "vision"))]
                if vis_models:
                    return vis_models
            def rank_model(m_id):
                ml = m_id.lower()
                if "llama-4" in ml or "maverick" in ml or "scout" in ml:
                    return 0
                if "70b" in ml or "qwen" in ml:
                    return 1
                if "llama" in ml:
                    return 2
                return 3
            chat_models.sort(key=rank_model)
            if chat_models:
                return chat_models
    except Exception:
        pass
    if vision_only:
        return ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]
    return ["meta-llama/llama-4-scout-17b-16e-instruct", "qwen-qwq-32b", "gemma2-9b-it"]

def call_llm_text(system_msg, user_prompt, api_key, temperature=0.35):
    clean_key = api_key.strip() if api_key else ""
    if not clean_key:
        return "", "⚠️ Cole a sua Chave Gratuita da Groq (começando com gsk_...) lá no topo direito e aperte ENTER!"

    last_error = ""
    if clean_key.startswith("gsk_"):
        headers_groq = {"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"}
        for groq_model in get_available_groq_models(clean_key)[:6]:
            try:
                r_groq = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers_groq,
                    json={
                        "model": groq_model,
                        "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": user_prompt}],
                        "temperature": temperature,
                        "max_tokens": 7500
                    },
                    timeout=95
                )
                if r_groq.status_code == 200:
                    out = clean_markdown(r_groq.json()["choices"][0]["message"]["content"])
                    if len(out) >= 20:
                        return out, None
                else:
                    last_error = f"HTTP {r_groq.status_code}: {r_groq.text[:180]}"
            except Exception as e_g:
                last_error = str(e_g)
        return "", f"❌ Erro na sua chave Groq: {last_error}"

    for model_id in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            g_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={clean_key}"
            r_gem = requests.post(
                g_url,
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": f"{system_msg}\n\n{user_prompt}"}]}], "generationConfig": {"temperature": temperature}},
                timeout=95
            )
            if r_gem.status_code == 200:
                out = clean_markdown(r_gem.json()["candidates"][0]["content"]["parts"][0]["text"])
                if len(out) >= 20:
                    return out, None
            else:
                last_error = f"HTTP {r_gem.status_code}: {r_gem.text[:180]}"
        except Exception as e_req:
            last_error = str(e_req)

    return "", f"❌ Chave inválida ({last_error}). Gere uma chave gratuita 'gsk_...' em https://console.groq.com/keys!"

def analyze_character_photo(uploaded_img, api_key):
    clean_key = api_key.strip() if api_key else ""
    if not clean_key:
        return None, "⚠️ Cole sua Chave Gratuita da Groq (gsk_...) no topo da página e aperte ENTER antes de analisar a foto!"

    img_bytes = uploaded_img.getvalue()
    mime_type = uploaded_img.type or "image/jpeg"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
        img_bytes = buf.getvalue()
        mime_type = "image/jpeg"
    except Exception:
        pass

    b64_data = base64.b64encode(img_bytes).decode("utf-8")
    vision_prompt = (
        "Analyze this character image and write a concise physical and clothing description in ONE English sentence "
        "(30 to 45 words) to lock visual identity across AI video scenes: biological sex/gender, apparent age, skin tone, exact hairstyle/color, facial hair, "
        "headwear, and exact outfit colors. Output ONLY the single English sentence."
    )

    last_err = ""
    if clean_key.startswith("gsk_"):
        headers_groq = {"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"}
        for v_mod in get_available_groq_models(clean_key, vision_only=True)[:4]:
            try:
                r_v = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers_groq,
                    json={
                        "model": v_mod,
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": vision_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}}
                        ]}],
                        "temperature": 0.1,
                        "max_tokens": 220
                    },
                    timeout=45
                )
                if r_v.status_code == 200:
                    desc = clean_markdown(r_v.json()["choices"][0]["message"]["content"])
                    if len(desc) >= 20:
                        return re.sub(r'\s+', ' ', desc).strip(), None
                else:
                    last_err = f"{v_mod}: HTTP {r_v.status_code}"
            except Exception as ex:
                last_err = str(ex)
        return None, f"Não foi possível ler a imagem ({last_err})."

    for model_id in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            g_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={clean_key}"
            payload = {"contents": [{"parts": [{"text": vision_prompt}, {"inline_data": {"mime_type": mime_type, "data": b64_data}}]}]}
            r_g = requests.post(g_url, json=payload, timeout=45)
            if r_g.status_code == 200:
                desc = clean_markdown(r_g.json()["candidates"][0]["content"]["parts"][0]["text"])
                if len(desc) >= 20:
                    return re.sub(r'\s+', ' ', desc).strip(), None
            else:
                last_err = f"HTTP {r_g.status_code}"
        except Exception as ex:
            last_err = str(ex)
    return None, f"Falha ao analisar foto: {last_err}"

def build_duo_reference_card(img_a_file, img_b_file, is_vertical=False):
    try:
        from PIL import Image
        if is_vertical:
            canvas = Image.new("RGB", (720, 1280), (240, 238, 232))
            for idx, f_obj in enumerate([img_a_file, img_b_file]):
                if f_obj is not None:
                    im = Image.open(io.BytesIO(f_obj.getvalue())).convert("RGB")
                    im.thumbnail((680, 600))
                    canvas.paste(im, ((720 - im.width) // 2, (idx * 640) + (640 - im.height) // 2))
        else:
            canvas = Image.new("RGB", (1280, 720), (240, 238, 232))
            for idx, f_obj in enumerate([img_a_file, img_b_file]):
                if f_obj is not None:
                    im = Image.open(io.BytesIO(f_obj.getvalue())).convert("RGB")
                    im.thumbnail((610, 680))
                    canvas.paste(im, ((idx * 640) + (640 - im.width) // 2, (720 - im.height) // 2))
        out_buf = io.BytesIO()
        canvas.save(out_buf, format="PNG")
        return out_buf.getvalue()
    except Exception:
        return None

def get_audio_duration_sec(audio_path, ffmpeg_exe):
    res = subprocess.run([ffmpeg_exe, '-i', audio_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return 60.0

def get_media_duration_sec(media_path, ffmpeg_exe):
    return get_audio_duration_sec(media_path, ffmpeg_exe)

def transcribe_uploaded_audio_chunks(audio_path, sr_lang_code, whisper_lang, api_key, ffmpeg_exe):
    dur = get_audio_duration_sec(audio_path, ffmpeg_exe)
    num_chunks = max(1, math.ceil(dur / 8.0))
    clean_key = api_key.strip() if api_key else ""
    work_dir = tempfile.mkdtemp()
    blocks = []

    try:
        if clean_key.startswith("gsk_"):
            wav_full = os.path.join(work_dir, "full_12k.wav")
            subprocess.run(
                [ffmpeg_exe, '-y', '-i', audio_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '12000', '-ac', '1', wav_full],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            if os.path.exists(wav_full) and os.path.getsize(wav_full) < 24 * 1024 * 1024:
                with open(wav_full, "rb") as wf:
                    r_w = requests.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {clean_key}"},
                        files={"file": ("audio.wav", wf, "audio/wav")},
                        data={
                            "model": "whisper-large-v3-turbo",
                            "language": whisper_lang,
                            "response_format": "verbose_json",
                            "timestamp_granularities[]": "word"
                        },
                        timeout=90
                    )
                if r_w.status_code == 200:
                    w_json = r_w.json()
                    buckets = [[] for _ in range(num_chunks)]
                    if w_json.get("words"):
                        for w_obj in w_json["words"]:
                            mid_t = ((w_obj.get("start", 0.0) or 0.0) + (w_obj.get("end", 0.0) or 0.0)) / 2.0
                            idx_b = min(num_chunks - 1, max(0, int(mid_t // 8.0)))
                            buckets[idx_b].append(w_obj.get("word", ""))
                    elif w_json.get("segments"):
                        for seg in w_json["segments"]:
                            mid_t = ((seg.get("start", 0.0) or 0.0) + (seg.get("end", 0.0) or 0.0)) / 2.0
                            idx_b = min(num_chunks - 1, max(0, int(mid_t // 8.0)))
                            buckets[idx_b].append(seg.get("text", ""))
                    if any(buckets):
                        for i in range(num_chunks):
                            start_s = i * 8
                            spoken_piece = " ".join(buckets[i]).strip() or f"Continuação visual da cena {i + 1}"
                            t1 = f"{start_s // 60:02d}:{start_s % 60:02d}"
                            t2 = f"{(start_s + 8) // 60:02d}:{(start_s + 8) % 60:02d}"
                            blocks.append(f"[{t1} - {t2}]\nLOCUÇÃO: {re.sub(r'\\s+', ' ', spoken_piece)}")
                        return "\n\n".join(blocks), dur, num_chunks

        import speech_recognition as sr
        recognizer = sr.Recognizer()
        for i in range(num_chunks):
            start_s = i * 8
            wav_chunk = os.path.join(work_dir, f"chunk_{i}.wav")
            cmd = [ffmpeg_exe, '-y', '-ss', str(start_s), '-i', audio_path, '-t', '8.0', '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', wav_chunk]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            spoken_piece = ""
            try:
                with sr.AudioFile(wav_chunk) as src:
                    adata = recognizer.record(src)
                spoken_piece = recognizer.recognize_google(adata, language=sr_lang_code)
            except Exception:
                spoken_piece = f"Continuação visual da cena {i + 1}"
            t1 = f"{start_s // 60:02d}:{start_s % 60:02d}"
            t2 = f"{(start_s + 8) // 60:02d}:{(start_s + 8) % 60:02d}"
            blocks.append(f"[{t1} - {t2}]\nLOCUÇÃO: {spoken_piece}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return "\n\n".join(blocks), dur, num_chunks

def generate_auto_cast_dna(topic, raw_script_sample, style_choice, api_key):
    clean_key = api_key.strip() if api_key else ""
    if not clean_key:
        return ""
    p_cast = (
        f"Analyze the topic '{topic}' and script excerpt below:\n{raw_script_sample[:1800]}\n\n"
        f"Does this video tell a story about specific recurring characters (e.g., biblical figures, historical characters, or a named protagonist)?\n"
        f"- If NO (city comparison, geography, curiosity documentary without recurring characters): output ONLY the word NONE.\n"
        f"- If YES: write ONE concise English Lock Sheet (max 45 words total) defining the fictionalized appearance: EXACT unchanging hairstyle, hair color, skin tone, age, biological sex, and period-accurate outfit color for the 1 or 2 main recurring characters (NEVER use modern clothes in ancient stories, NEVER mention celebrity names).\n"
        f"Output ONLY 'NONE' or the single-line English character lock description."
    )
    out, err = call_llm_text("Output ONLY 'NONE' or a concise single-line English character visual lock.", p_cast, clean_key, temperature=0.1)
    if err or not out or out.strip().upper().startswith("NONE"):
        return ""
    return sanitize_visual_for_veo_safety(re.sub(r'[\r\n"]+', ' ', out).strip())

def auto_adapt_dialogue_cast(topic, style_choice, api_key):
    clean_key = api_key.strip() if api_key else ""
    if not clean_key or not topic.strip():
        return None
    p = (
        f"Video Topic / Story: '{topic}' | Visual Style: '{style_choice}'.\n"
        f"Define the 2 main speaking characters for this exact theme and era (use strictly period-accurate ancient/historical clothing if biblical/historical, NEVER modern suits or living rooms unless the theme is modern!).\n"
        f"Return STRICTLY 4 lines in this exact format in English:\n"
        f"DNA_A: <fictional character A gender, age, skin tone, exact hair, and period-accurate outfit in 25-35 words>\n"
        f"VOICE_A: <character A voice gender, age, pitch in Hz, and tone in 10-15 words>\n"
        f"DNA_B: <fictional character B gender, age, skin tone, exact hair, and period-accurate outfit in 25-35 words>\n"
        f"VOICE_B: <character B voice gender, age, pitch in Hz, and tone in 10-15 words>"
    )
    out, err = call_llm_text("Output ONLY the 4 requested lines (DNA_A, VOICE_A, DNA_B, VOICE_B).", p, clean_key, temperature=0.2)
    if err or not out:
        return None
    res = {}
    for ln in out.splitlines():
        for k in ("DNA_A", "VOICE_A", "DNA_B", "VOICE_B"):
            if ln.strip().upper().startswith(k + ":"):
                res[k] = sanitize_visual_for_veo_safety(ln.split(":", 1)[1].strip())
    return res if ("DNA_A" in res and "DNA_B" in res) else None

def generate_ai_script(title, num_scenes, lang_label, style_choice, audio_mode, aspect_framing, char_a_desc="", char_b_desc="", single_char_desc="", api_key=""):
    lang_en = LANGUAGES[lang_label]["name_en"]
    if "Diálogo" in audio_mode:
        ca_info = char_a_desc.strip() if char_a_desc.strip() else f"Main Character A from '{title}' in period-accurate attire"
        cb_info = char_b_desc.strip() if char_b_desc.strip() else f"Main Character B from '{title}' in period-accurate attire"
        prompt_text = (
            f"You are a master screenwriter creating an authentic, high-retention dialogue video.\n"
            f"Story / Situation: '{title}' | Framing: {aspect_framing} | Total Scenes: EXACTLY {num_scenes} scenes (8s each).\n"
            f"Character A: {ca_info}\nCharacter B: {cb_info}\n\n"
            f"RULES:\n"
            f"1. STRICT CHRONOLOGICAL PROGRESSION: Every scene MUST advance the story forward without repeating lines.\n"
            f"2. ERA-APPROPRIATE SETTING: Set every [CENA: ...] in the authentic location of '{title}'.\n"
            f"3. ONE SPEAKER PER SCENE: Alternate PERSONAGEM A and PERSONAGEM B speaking authentic {lang_en} (12 to 17 words).\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line, ZERO blank lines inside a block):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Continuous shot in the authentic setting in English, active speaker talking while listener is silent, zero text]\n"
            f"PERSONAGEM A: Authentic line in {lang_en} (12-17 words)."
        )
    else:
        if single_char_desc.strip():
            char_hint = f"the exact protagonist ({single_char_desc.strip()}) with identical hair and outfit in every scene, mouth closed"
        elif "Palito" in style_choice:
            char_hint = "white stick figure characters dressed appropriately for the story's era"
        elif "Cartoon" in style_choice:
            char_hint = "3D stylized animated characters with IDENTICAL hairstyle/color in every scene and STRICTLY PERIOD-ACCURATE clothing"
        else:
            char_hint = "pure cinematic B-roll documentary footage of the real location/era (ZERO TV anchors, ZERO people speaking to camera, ZERO snow in Brazil, ZERO ocean in inland Minas Gerais)"

        prompt_text = (
            f"You are a master storyteller and fact-checked documentary screenwriter.\n"
            f"Topic / Story Title: '{title}' | Total Scenes: Write EXACTLY {num_scenes} scenes (8s each).\n\n"
            f"RULES:\n"
            f"1. STRICT LINEAR CHRONOLOGY (1 TO {num_scenes}): Setup -> development -> climax -> resolution -> Call-to-Action.\n"
            f"2. VISUAL CONSISTENCY & PURE B-ROLL: Visuals feature {char_hint}. NEVER show TV presenters, people doing thumbs-up, maps with text, or snow in tropical/Brazilian cities!\n"
            f"3. 100% NATIVE NAMES IN {lang_en}: Use translated names (e.g. 'Davi' and 'Golias' in Portuguese) and NEVER write normal words in ALL CAPS.\n"
            f"4. DISTINCT VOCABULARY PER SCENE: 14 to 18 words per LOCUÇÃO. All people on screen keep mouths closed.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Single continuous shot in English, mouths closed, zero text on screen]\n"
            f"LOCUÇÃO: Engaging narration in {lang_en} (14-18 words)."
        )

    temp_val = 0.35 if "Diálogo" in audio_mode else 0.22
    sys_msg = "Output ONLY the requested formatted script scenes in strict linear chronological order."
    out, err = call_llm_text(sys_msg, prompt_text, api_key, temperature=temp_val)
    if err:
        return "", err

    lines_fixed = []
    for ln in out.splitlines():
        if re.match(r'^(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|PERSONAGEM\s*[AB12])\s*:', ln.strip(), re.IGNORECASE):
            prefix, body = ln.split(":", 1)
            lines_fixed.append(f"{prefix.strip()}: {fix_pronunciation(body, lang_label)}")
        else:
            lines_fixed.append(ln)
    return "\n".join(lines_fixed), None

def generate_seo_and_thumbnail_kit(title, script_text, lang_label, aspect_label, style_choice, char_dna, api_key):
    lang_en = LANGUAGES[lang_label]["name_en"]
    orient = "9:16 vertical cover (TikTok/Shorts/Reels)" if "9:16" in aspect_label else "16:9 horizontal YouTube Thumbnail"
    seo_prompt = (
        f"Based on the video topic '{title}' and the script below, generate a complete high-CTR publishing kit in {lang_en} "
        f"(except the Image Prompt which MUST be in English).\n\nScript:\n{script_text[:3500]}\n\nStyle: {style_choice}\nCharacter DNA: {char_dna}\n\n"
        f"Deliver cleanly organized with these exact headings:\n"
        f"1. 🔥 5 TÍTULOS MAGNÉTICOS DE ALTO CTR\n"
        f"2. 📝 DESCRIÇÃO OTIMIZADA COM SEO + CAPÍTULOS (00:00)\n"
        f"3. 🏷️ 20 TAGS DE ALTO VOLUME (comma-separated)\n"
        f"4. 🖼️ PROMPT PRONTO PARA CAPA / THUMBNAIL ({orient}, in English, vivid visual hook, period-accurate wardrobe, zero gibberish text)"
    )
    return call_llm_text("You are a YouTube & TikTok viral growth strategist.", seo_prompt, api_key, temperature=0.5)

# ======= AUTO-FATIADOR + DIRETOR VISUAL B-ROLL DOCUMENTAL PURO =======
def split_spoken_into_8s_chunks(spoken_text, max_words=18):
    words_total = spoken_text.split()
    if len(words_total) <= max_words + 2:
        return [spoken_text.strip()]

    sentences = re.split(r'(?<=[.!?])\s+', spoken_text.strip())
    raw_chunks = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent.split()) <= max_words:
            raw_chunks.append(sent)
        else:
            clauses = re.split(r'(?<=[;:—,])\s+|\s+(?=—)', sent)
            curr = ""
            for cl in clauses:
                cl = cl.strip()
                if not cl:
                    continue
                cand = f"{curr} {cl}".strip() if curr else cl
                if len(cand.split()) <= max_words:
                    curr = cand
                else:
                    if curr:
                        raw_chunks.append(curr)
                    if len(cl.split()) <= max_words + 2:
                        curr = cl
                    else:
                        c_words = cl.split()
                        step = max(12, min(max_words, math.ceil(len(c_words) / math.ceil(len(c_words) / max_words))))
                        for i in range(0, len(c_words), step):
                            part = " ".join(c_words[i:i + step])
                            if i + step < len(c_words):
                                raw_chunks.append(part)
                            else:
                                curr = part
            if curr:
                raw_chunks.append(curr)

    merged = []
    for ch in raw_chunks:
        if merged and (len(ch.split()) < 8 or len(merged[-1].split()) < 9) and (len(merged[-1].split()) + len(ch.split()) <= 22):
            merged[-1] = f"{merged[-1]} {ch}".strip()
        else:
            merged.append(ch)
    return merged

def clean_visual_for_flow(vis_text):
    if not vis_text:
        return ""
    v = re.sub(
        r'(?:texto|placar|mapa|tela\s+final)[^,\]]*?(?:na tela|piscando|animado|com\s+2\s+v[íi]deos)?\s*:?\s*["“”]?.*?["“”]?(?:$|\+|/)',
        '',
        vis_text,
        flags=re.IGNORECASE
    ).strip(" /+-:,")
    return sanitize_visual_for_veo_safety(v, is_narration_broll=True) if len(v) >= 8 else ""

def looks_non_english_visual(text):
    if not text:
        return True
    if re.search(r'[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]', text):
        return True
    pt_markers = r'\b(vista|aerea|imagem|imagens|tela|dividida|predios|cidade|ruas|morros|carretas|comercio|feiras|padarias|por do sol|camera|mostrando|pessoas|familias|centro|bairro|menino|gigante|pedra|vale|placar|decisao)\b'
    norm_t = unicodedata.normalize('NFD', text.lower())
    norm_t = ''.join(c for c in norm_t if unicodedata.category(c) != 'Mn')
    return bool(re.search(pt_markers, norm_t, flags=re.IGNORECASE))

def extract_scenes_for_prompts(raw_script, lang_label, preserve_1to1_blocks=False, allow_empty_speech=False):
    if not raw_script or not raw_script.strip():
        return []

    if re.search(r'===\s*CENA\s*\d+\s*===', raw_script, re.IGNORECASE):
        prompt_parts = re.split(r'===\s*CENA\s*\d+\s*===', raw_script, flags=re.IGNORECASE)
        direct_scenes = []
        for pp in prompt_parts:
            pp = pp.strip()
            if not pp:
                continue
            m_q = re.findall(r'"([^"]{3,})"', pp)
            if m_q:
                spoken_line = fix_pronunciation(m_q[-1].strip(), lang_label)
                direct_scenes.append({
                    "visual": "Cinematic continuous shot",
                    "raw_visual_hint": "",
                    "spoken": spoken_line,
                    "speaker": "NARRATOR",
                    "needs_ai_visual": False
                })
        if direct_scenes:
            return direct_scenes

    pre = raw_script.strip()
    pre = re.sub(r'(?<!^)\n*(\[\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\])', r'\n\n\1', pre)
    pre = re.sub(r'(\[\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\])\s*\n+\s*', r'\1\n', pre)
    pre = re.sub(r'(?<!\]\n)\n*(\[(?:CENA|SCENE)\s*:)', r'\n\n\1', pre, flags=re.IGNORECASE)
    pre = re.sub(r'(\[\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\])\s*\n+\s*(\[(?:CENA|SCENE)\s*:)', r'\1\n\2', pre, flags=re.IGNORECASE)
    pre = re.sub(
        r'(\[(?:CENA|SCENE)\s*:[^\]]*\])\s*\n+\s*(?=(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala|PERSONAGEM))',
        r'\1\n',
        pre,
        flags=re.IGNORECASE
    )

    blocks = re.split(r'\n\s*\n', pre.strip())
    camera_angles = [
        "Wide cinematic aerial establishing shot",
        "Smooth gliding drone tracking shot",
        "Medium cinematic architectural street-level shot",
        "Sweeping golden-hour panoramic camera movement",
        "Dynamic push-in shot with natural lighting"
    ]

    scenes = []
    pending_orphan_visual = ""

    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        visual, spoken_parts, speaker_tag = "", [], "NARRATOR"

        for line in lines:
            if re.match(r'^\[?\d{1,2}:\d{2}(?:\s*-\s*\d{1,2}:\d{2})?\]?$', line):
                continue
            if re.match(r'^(?:ROUND\s*\d+|ABERTURA|VEREDITO\s+FINAL|ENCERRAMENTO|INTRODU[ÇC][ÃA]O|CAP[ÍI]TULO\s*\d+|PARTE\s*\d+)\b', line, re.IGNORECASE) and ":" not in line:
                continue

            m_cena = re.search(r'^\[?(?:CENA|SCENE)\s*:\s*(.+?)\]?$', line, re.IGNORECASE)
            m_pa = re.search(r'^PERSONAGEM\s*(?:A|1)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
            m_pb = re.search(r'^PERSONAGEM\s*(?:B|2)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
            m_loc = re.search(r'^(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)

            if m_cena:
                visual = clean_visual_for_flow(m_cena.group(1).strip())
            elif m_pa:
                speaker_tag = "A"
                spoken_parts.append(fix_pronunciation(m_pa.group(1).strip(), lang_label))
            elif m_pb:
                speaker_tag = "B"
                spoken_parts.append(fix_pronunciation(m_pb.group(1).strip(), lang_label))
            elif m_loc:
                speaker_tag = "NARRATOR"
                spoken_parts.append(fix_pronunciation(m_loc.group(1).strip(), lang_label))
            else:
                spoken_parts.append(fix_pronunciation(line, lang_label))

        if not visual and pending_orphan_visual:
            visual = pending_orphan_visual
            pending_orphan_visual = ""

        full_spoken = " ".join(p for p in spoken_parts if p).strip()

        if not full_spoken and visual and not allow_empty_speech:
            pending_orphan_visual = visual
            continue
        if not full_spoken and not visual:
            continue

        if preserve_1to1_blocks:
            chunks = [full_spoken] if full_spoken else [""]
        else:
            chunks = split_spoken_into_8s_chunks(full_spoken, max_words=18) if full_spoken else [""]

        has_user_vis = bool(visual.strip())

        for c_idx, ch_txt in enumerate(chunks):
            if not ch_txt.strip() and not allow_empty_speech:
                continue
            cam_prefix = camera_angles[c_idx % len(camera_angles)]
            if has_user_vis:
                varied_vis = f"{cam_prefix} — {visual}" if len(chunks) > 1 else visual
                needs_ai = looks_non_english_visual(visual)
            else:
                varied_vis = ""
                needs_ai = True

            scenes.append({
                "visual": varied_vis,
                "raw_visual_hint": visual,
                "spoken": ch_txt,
                "speaker": speaker_tag,
                "needs_ai_visual": needs_ai
            })

    return scenes

def enrich_scenes_with_ai_visuals(scenes, topic_hint, style_choice, audio_mode, char_lock_desc, api_key, progress_placeholder=None):
    pending_indices = [i for i, sc in enumerate(scenes) if sc.get("needs_ai_visual")]
    if not pending_indices:
        return scenes

    clean_key = api_key.strip() if api_key else ""
    is_broll_doc = ("Diálogo" not in audio_mode and not char_lock_desc.strip() and "Realista" in style_choice)

    if not clean_key:
        for i in pending_indices:
            hint = scenes[i].get("raw_visual_hint", "").strip()
            scenes[i]["visual"] = hint if hint else "Cinematic 4K aerial and street B-roll footage matching the topic, zero text, zero presenters"
        return scenes

    if "Diálogo" in audio_mode:
        subject_rule = f"Shot in the authentic setting and era of '{topic_hint or 'the story'}', active speaker talking while listener is silent, period-accurate attire."
    elif char_lock_desc.strip():
        subject_rule = f"Keep character appearance 100% identical across scenes ({char_lock_desc.strip()}), mouths closed, period-accurate setting."
    elif "Palito" in style_choice:
        subject_rule = "Feature simple white stick figure characters dressed appropriately for the story era."
    elif "Cartoon" in style_choice:
        subject_rule = "Feature 3D stylized animated characters with IDENTICAL hair color/style across all scenes and STRICTLY PERIOD-ACCURATE wardrobe."
    else:
        subject_rule = (
            "PURE CINEMATIC B-ROLL DOCUMENTARY FOOTAGE ONLY: Show real-world aerial drone views, avenues, parks, universities, highways, or architecture matching the exact geography/climate. "
            "STRICTLY FORBIDDEN: NEVER show TV presenters, news anchors, men in polo shirts talking to camera, thumbs-up gestures, scoreboards, maps with text, subscribe buttons, snow in Brazil, or ocean beaches in inland Minas Gerais! "
            "Even if the narration mentions 'score 1 to 0', 'leave a like', 'comment below', or 'subscribe', illustrate ONLY breathtaking scenic B-roll of the cities/landscapes!"
        )

    batch_size = 25
    total_batches = math.ceil(len(pending_indices) / batch_size)

    for b_num, start in enumerate(range(0, len(pending_indices), batch_size), 1):
        batch_idxs = pending_indices[start:start + batch_size]
        if progress_placeholder is not None:
            progress_placeholder.info(f"🎬 Diretor Visual IA criando B-Roll puro sem apresentadores/erros (Lote {b_num}/{total_batches})...")

        lines_in = []
        for idx in batch_idxs:
            sc = scenes[idx]
            hint_part = f" | Hint: {sc['raw_visual_hint']}" if sc.get("raw_visual_hint") else ""
            lines_in.append(f"{idx + 1}|Narration: {sc['spoken']}{hint_part}")

        user_p = (
            f"Video Overall Topic: '{topic_hint or 'Documentary / Story'}'\n"
            f"STRICT VISUAL RULE: {subject_rule}\n\n"
            f"For each numbered item below, write ONE specific 8-second continuous camera shot in ENGLISH (16 to 26 words). "
            f"ZERO on-screen text, ZERO signs, ZERO maps, ZERO presenters looking at camera, ZERO snow in tropical/Brazilian cities.\n\n"
            f"Format EVERY output line strictly as:\nNUMBER|English visual shot description\n\nITEMS:\n" + "\n".join(lines_in)
        )
        out_txt, err = call_llm_text("You are an expert AI director for Google Veo. Output ONLY 'NUMBER|English visual description' lines.", user_p, clean_key, temperature=0.2)

        parsed_map = {}
        if not err and out_txt:
            for ln in out_txt.splitlines():
                m = re.match(r'^\s*(\d+)\s*\|\s*(.+)$', ln.strip())
                if m:
                    s_num = int(m.group(1))
                    vis_en = sanitize_visual_for_veo_safety(re.sub(r'[\r\n"]+', ' ', m.group(2)).strip(" .-"), is_narration_broll=is_broll_doc)
                    if len(vis_en) >= 10:
                        parsed_map[s_num] = vis_en

        for idx in batch_idxs:
            if (idx + 1) in parsed_map:
                scenes[idx]["visual"] = parsed_map[idx + 1]
                scenes[idx]["needs_ai_visual"] = False
            elif not scenes[idx].get("visual"):
                scenes[idx]["visual"] = f"Sweeping golden-hour aerial drone shot of {topic_hint or 'the city avenues and green hills'}, photorealistic 4K, zero text"

    if progress_placeholder is not None:
        progress_placeholder.empty()
    return scenes

# ================= MOTOR LOCAL FFMPEG.WASM v3.3 (ANTI-DESLIZAMENTO DE AUDIO + ANTI-CLONE) =================
FFMPEG_WASM_HTML_LINES = [
'<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8" />',
'<title>Estudio Pro — Montador Local FFmpeg.wasm v3.3</title>',
'<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>',
'<script src="https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.11.6/dist/ffmpeg.min.js" onerror="var s=document.createElement(\'script\');s.src=\'https://unpkg.com/@ffmpeg/ffmpeg@0.11.6/dist/ffmpeg.min.js\';document.head.appendChild(s);"></script>',
'<style>',
'* { box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }',
'body { margin: 0; padding: 12px; background: #0f172a; color: #f8fafc; border-radius: 12px; }',
'.card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 16px; }',
'.top-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }',
'.badge { background: #065f46; color: #6ee7b7; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }',
'.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }',
'@media (max-width: 720px) { .grid2 { grid-template-columns: 1fr; } }',
'.dropzone { border: 2px dashed #3b82f6; background: #0f172a; border-radius: 10px; padding: 15px; text-align: center; cursor: pointer; transition: 0.2s; }',
'.dropzone:hover { border-color: #60a5fa; background: #172554; }',
'label.lbl { display: block; font-size: 12.5px; font-weight: 600; color: #cbd5e1; margin-bottom: 5px; }',
'textarea.script-box { width: 100%; background: #0f172a; color: #f1f5f9; border: 1px solid #475569; border-radius: 8px; padding: 8px; font-size: 12px; resize: vertical; margin-bottom: 10px; }',
'select, input[type="range"] { width: 100%; padding: 8px; border-radius: 8px; background: #0f172a; color: #fff; border: 1px solid #475569; font-size: 13px; }',
'.chk-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #e2e8f0; margin: 7px 0; cursor: pointer; }',
'.btn-main { width: 100%; padding: 13px; border: none; border-radius: 10px; font-size: 15px; font-weight: 700; cursor: pointer; background: linear-gradient(90deg, #2563eb, #1d4ed8); color: #fff; }',
'.btn-main:disabled { opacity: 0.55; cursor: not-allowed; }',
'.btn-sec { background: #334155; color: #f1f5f9; border: 1px solid #475569; border-radius: 8px; padding: 7px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }',
'.prog-wrap { background: #0f172a; border-radius: 999px; height: 12px; overflow: hidden; margin: 10px 0 6px; border: 1px solid #334155; display: none; }',
'.prog-bar { background: linear-gradient(90deg, #10b981, #3b82f6); height: 100%; width: 0%; transition: width 0.2s; }',
'.status-txt { font-size: 13px; color: #93c5fd; min-height: 20px; margin-bottom: 6px; }',
'.dl-box { display: none; background: #064e3b; border: 1px solid #10b981; border-radius: 10px; padding: 14px; margin-top: 12px; }',
'.dl-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 10px; margin-top: 10px; }',
'.dl-btn { display: block; text-align: center; padding: 12px; border-radius: 8px; font-weight: 700; text-decoration: none; font-size: 14px; }',
'.dl-mp4 { background: #10b981; color: #052e16; }',
'.dl-srt { background: #0f172a; color: #f8fafc; border: 1px solid #34d399; }',
'.log-box { max-height: 210px; overflow-y: auto; background: #020617; border: 1px solid #1e293b; border-radius: 8px; padding: 10px; font-family: monospace; font-size: 11.5px; color: #94a3b8; margin-top: 10px; display: none; }',
'</style></head><body>',
'<div class="card">',
'  <div class="top-row">',
'    <div>',
'      <strong style="font-size:16px;color:#60a5fa;">⚡ Montador Local FFmpeg.wasm v3.3 (Trava Anti-Deslizamento + Zero Clones)</strong>',
'      <div style="font-size:12px;color:#94a3b8;margin-top:2px;">Une <b>950 MB+</b> sem upload e mantém sincronia cravada mesmo se faltarem cenas no Flow! Cenas no roteiro: <b id="sc-count-lbl" style="color:#34d399;">0 cenas</b>.</div>',
'    </div>',
'    <div style="display:flex;gap:8px;align-items:center;">',
'      <span class="badge">v3.3 Sincronia Cravada</span>',
'      <button class="btn-sec" id="open-tab-btn">🖥️ Abrir em Aba Dedicada (+RAM)</button>',
'    </div>',
'  </div>',
'  <label class="lbl">📜 Roteiro Completo OU conteúdo de <code>Prompts_Flow.txt</code>:</label>',
'  <textarea id="inp-script" class="script-box" rows="4" placeholder="Cole aqui o roteiro completo ou o texto de Prompts_Flow.txt..."></textarea>',
'  <div class="grid2">',
'    <div>',
'      <label class="lbl">📦 1. Selecione o .ZIP gigante (0.9GB+) ou vários .MP4:</label>',
'      <div class="dropzone" onclick="document.getElementById(\'inp-videos\').click()">',
'        <input type="file" id="inp-videos" multiple accept=".zip,.mp4,video/mp4,application/zip" style="display:none" />',
'        <div id="vid-file-label" style="font-size:13px;color:#93c5fd;font-weight:600;">Clique aqui para escolher o .ZIP ou todos os .MP4<br/><span style="font-size:11px;color:#64748b;font-weight:400;">Leitura direta no seu PC (0 bytes enviados)</span></div>',
'      </div>',
'      <div class="grid2" style="margin-top:10px;">',
'        <div><label class="lbl">🎙️ 2A. Seu Áudio / Locução (Opcional):</label><input type="file" id="inp-voice" accept="audio/*" style="font-size:11.5px;width:100%;color:#cbd5e1;" /></div>',
'        <div><label class="lbl">🎵 2B. Música de Fundo (Opcional):</label><input type="file" id="inp-bgm" accept="audio/*" style="font-size:11.5px;width:100%;color:#cbd5e1;" /></div>',
'      </div>',
'      <div id="bgm-vol-wrap" style="margin-top:8px;display:none;">',
'        <label class="lbl">🔉 Volume da Música de Fundo: <span id="bgm-vol-val">12</span>%</label>',
'        <input type="range" id="inp-bgm-vol" min="3" max="40" value="12" oninput="document.getElementById(\'bgm-vol-val\').innerText=this.value" />',
'      </div>',
'    </div>',
'    <div>',
'      <label class="lbl">🧭 3. Como ordenar e filtrar os clipes?</label>',
'      <select id="sel-sort">',
'        <option value="whisper">🗣️ Pareamento IA por Voz v3.3 (Escolhe Melhor Take + Elimina Clones)</option>',
'        <option value="chron_flow">🕒 Ordem de Geração do Flow / Nome (Para vídeos mudos)</option>',
'        <option value="alpha">🔢 Ordem Alfabética Pura dos Nomes</option>',
'      </select>',
'      <label class="chk-row" style="margin-top:10px;"><input type="checkbox" id="chk-drop-muted" checked /><span>🧹 Descartar clipes mudos e <b>takes duplicados da mesma fala</b></span></label>',
'      <label class="chk-row"><input type="checkbox" id="chk-pad-missing" checked /><span>🛡️ <b>Trava Anti-Deslizamento (Áudio 2A):</b> Preencher buracos de cenas que falharam no Flow para nunca adiantar imagens nem cortar o final da sua locução!</span></label>',
'      <label class="chk-row"><input type="checkbox" id="chk-single-file" checked /><span>🎬 Entregar em <b>1 Único Arquivo .MP4 Completo</b></span></label>',
'    </div>',
'  </div>',
'  <div style="margin-top:14px;"><button class="btn-main" id="btn-run">🚀 MONTAR VÍDEO COMPLETO SINCRONIZADO (.MP4)</button></div>',
'  <div class="prog-wrap" id="prog-wrap"><div class="prog-bar" id="prog-bar"></div></div>',
'  <div class="status-txt" id="status-txt"></div>',
'  <div class="dl-box" id="dl-box">',
'    <div id="dl-summary" style="font-weight:700;color:#6ee7b7;font-size:14px;"></div>',
'    <div id="dl-missing" style="font-size:12px;color:#fde68a;margin-top:4px;"></div>',
'    <div id="dl-buttons-container" class="dl-grid"></div>',
'    <video id="preview-vid" controls style="width:100%;max-height:300px;margin-top:12px;border-radius:8px;background:#000;display:none;"></video>',
'  </div>',
'  <div class="log-box" id="log-box"></div>',
'</div>',
'<script>',
'const CONFIG = __CONFIG_JSON__;',
'const scriptTextarea = document.getElementById("inp-script");',
'scriptTextarea.value = CONFIG.rawScript || "";',
'const yieldUI = () => new Promise(r => setTimeout(r, 15));',
'function fixPronJS(t) {',
'  if (!t) return "";',
'  let s = t.trim();',
'  if (CONFIG.whisperLang === "pt") {',
'    s = s.replace(/\\bIBGE\\b/g, "I B G E").replace(/\\bUFJF\\b/g, "U F J F").replace(/\\bUFU\\b/g, "U F U").replace(/\\bUFMG\\b/g, "U F M G").replace(/\\bIDH\\b/g, "I D H").replace(/\\bPIB\\b/g, "P I B").replace(/\\bBH\\b/g, "Belo Horizonte").replace(/\\bJF\\b/g, "Juiz de Fora").replace(/\\bMG\\b/g, "Minas Gerais").replace(/\\bBR[-\\s]*040\\b/gi, "B R zero quarenta").replace(/R\\$\\s*(\\d+)/g, "$1 reais").replace(/(\\d+)\\s*km\\b/gi, "$1 quilometros").replace(/(\\d+)\\s*%/g, "$1 por cento").replace(/\\bGoliath\\b/g, "Golias").replace(/\\bDavid\\b/g, "Davi");',
'  }',
'  return s.replace(/\\s+/g, " ").trim();',
'}',
'function splitSpoken8sJS(spokenText, maxWords = 18) {',
'  const wordsTotal = spokenText.split(/\\s+/).filter(Boolean);',
'  if (wordsTotal.length <= maxWords + 2) return [spokenText.trim()];',
'  const sentences = spokenText.trim().split(/(?<=[.!?])\\s+/);',
'  const rawChunks = [];',
'  for (let sent of sentences) {',
'    sent = sent.trim(); if (!sent) continue;',
'    if (sent.split(/\\s+/).length <= maxWords) { rawChunks.push(sent); } else {',
'      const clauses = sent.split(/(?<=[;:—,])\\s+|\\s+(?=—)/); let curr = "";',
'      for (let cl of clauses) {',
'        cl = cl.trim(); if (!cl) continue;',
'        const cand = curr ? (curr + " " + cl).trim() : cl;',
'        if (cand.split(/\\s+/).length <= maxWords) { curr = cand; } else {',
'          if (curr) rawChunks.push(curr);',
'          const cw = cl.split(/\\s+/);',
'          if (cw.length <= maxWords + 2) { curr = cl; } else {',
'            const step = Math.max(12, Math.min(maxWords, Math.ceil(cw.length / Math.ceil(cw.length / maxWords))));',
'            for (let i = 0; i < cw.length; i += step) {',
'              const part = cw.slice(i, i + step).join(" ");',
'              if (i + step < cw.length) rawChunks.push(part); else curr = part;',
'            }',
'          }',
'        }',
'      }',
'      if (curr) rawChunks.push(curr);',
'    }',
'  }',
'  const merged = [];',
'  for (const ch of rawChunks) {',
'    const cwLen = ch.split(/\\s+/).length;',
'    const prevLen = merged.length ? merged[merged.length - 1].split(/\\s+/).length : 99;',
'    if (merged.length && (cwLen < 8 || prevLen < 9) && (prevLen + cwLen <= 22)) merged[merged.length - 1] = (merged[merged.length - 1] + " " + ch).trim();',
'    else merged.push(ch);',
'  }',
'  return merged;',
'}',
'function parseScriptScenesJS(raw) {',
'  if (!raw || !raw.trim()) return [];',
'  if (/===\\s*CENA\\s*\\d+\\s*===/i.test(raw)) {',
'    const parts = raw.split(/===\\s*CENA\\s*\\d+\\s*===/i).map(s => s.trim()).filter(Boolean);',
'    const direct = [];',
'    for (const p of parts) {',
'      const matches = [...p.matchAll(/"([^"]{3,})"/g)];',
'      if (matches.length > 0) direct.push({ spoken: fixPronJS(matches[matches.length - 1][1]) });',
'    }',
'    if (direct.length > 0) return direct;',
'  }',
'  let pre = raw.trim();',
'  pre = pre.replace(/(?<!^)\\n*(\\[\\d{1,2}:\\d{2}\\s*-\\s*\\d{1,2}:\\d{2}\\])/g, "\\n\\n$1");',
'  pre = pre.replace(/(\\[\\d{1,2}:\\d{2}\\s*-\\s*\\d{1,2}:\\d{2}\\])\\s*\\n+\\s*/g, "$1\\n");',
'  pre = pre.replace(/(\\[(?:CENA|SCENE)\\s*:[^\\]]*\\])\\s*\\n+\\s*(?=(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala|PERSONAGEM))/gi, "$1\\n");',
'  const blocks = pre.trim().split(/\\n\\s*\\n/);',
'  const outScenes = [];',
'  for (const block of blocks) {',
'    const lines = block.split(/\\r?\\n/).map(l => l.trim()).filter(Boolean);',
'    const spokenParts = [];',
'    for (const line of lines) {',
'      if (/^\\[?\\d{1,2}:\\d{2}(?:\\s*-\\s*\\d{1,2}:\\d{2})?\\]?$/.test(line)) continue;',
'      if (/^(?:ROUND\\s*\\d+|ABERTURA|VEREDITO\\s+FINAL|ENCERRAMENTO|INTRODU[ÇC][ÃA]O|CAP[ÍI]TULO\\s*\\d+|PARTE\\s*\\d+)\\b/i.test(line) && !line.includes(":")) continue;',
'      if (/^\\[?(?:CENA|SCENE)\\s*:\\s*(.+?)\\]?$/i.test(line)) continue;',
'      const mSpk = line.match(/^(?:PERSONAGEM\\s*(?:A|B|1|2)|LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala)\\s*(?:\\(.*?\\))?\\s*:\\s*(.+)/i);',
'      if (mSpk) spokenParts.push(fixPronJS(mSpk[1])); else spokenParts.push(fixPronJS(line));',
'    }',
'    const fullSpoken = spokenParts.filter(Boolean).join(" ").trim();',
'    if (!fullSpoken) continue;',
'    if (CONFIG.preserve1to1) { outScenes.push({ spoken: fullSpoken }); } else {',
'      for (const ch of splitSpoken8sJS(fullSpoken, 18)) { if (ch) outScenes.push({ spoken: ch }); }',
'    }',
'  }',
'  return outScenes;',
'}',
'function getActiveScenes() {',
'  const edited = scriptTextarea.value.trim();',
'  if (!edited) return [];',
'  if (edited === (CONFIG.rawScript || "").trim() && CONFIG.scenes && CONFIG.scenes.length) return CONFIG.scenes;',
'  return parseScriptScenesJS(edited);',
'}',
'function refreshSceneBadge() { document.getElementById("sc-count-lbl").innerText = getActiveScenes().length + " cenas"; }',
'refreshSceneBadge(); scriptTextarea.addEventListener("input", refreshSceneBadge);',
'document.getElementById("inp-bgm").addEventListener("change", (e) => { document.getElementById("bgm-vol-wrap").style.display = e.target.files.length ? "block" : "none"; });',
'document.getElementById("inp-videos").addEventListener("change", (e) => {',
'  const files = [...e.target.files]; if (!files.length) return;',
'  const totalMB = (files.reduce((acc, f) => acc + f.size, 0) / 1048576).toFixed(1);',
'  document.getElementById("vid-file-label").innerHTML = "✅ <b>" + files.length + " arquivo(s) (" + totalMB + " MB)</b><br/><span style=\'font-size:11px;color:#34d399;\'>Pronto para colar sem upload!</span>";',
'});',
'document.getElementById("open-tab-btn").addEventListener("click", () => {',
'  scriptTextarea.textContent = scriptTextarea.value;',
'  const blob = new Blob([document.documentElement.outerHTML], { type: "text/html;charset=utf-8" });',
'  window.open(URL.createObjectURL(blob), "_blank");',
'});',
'function logMsg(msg) {',
'  const lb = document.getElementById("log-box"); lb.style.display = "block";',
'  const div = document.createElement("div"); div.textContent = "[" + new Date().toLocaleTimeString() + "] " + msg;',
'  lb.appendChild(div); lb.scrollTop = lb.scrollHeight;',
'}',
'function setProgress(pct, text) {',
'  document.getElementById("prog-wrap").style.display = "block";',
'  document.getElementById("prog-bar").style.width = Math.min(100, Math.max(0, pct)) + "%";',
'  document.getElementById("status-txt").innerText = text;',
'}',
'function normalizeText(str) {',
'  if (!str) return "";',
'  return str.toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").replace(/[^a-z0-9\\s]/g, " ").replace(/\\s+/g, " ").trim();',
'}',
'function levenshteinRatio(a, b) {',
'  if (!a && !b) return 100; if (!a || !b) return 0;',
'  const m = a.length, n = b.length, dp = new Uint16Array(n + 1);',
'  for (let j = 0; j <= n; j++) dp[j] = j;',
'  for (let i = 1; i <= m; i++) {',
'    let prev = dp[0]; dp[0] = i;',
'    for (let j = 1; j <= n; j++) {',
'      const temp = dp[j], cost = a[i - 1] === b[j - 1] ? 0 : 1;',
'      dp[j] = Math.min(dp[j] + 1, dp[j - 1] + 1, prev + cost); prev = temp;',
'    }',
'  }',
'  return ((m + n - dp[n]) / (m + n)) * 100;',
'}',
'function tokenSortRatio(a, b) {',
'  return levenshteinRatio(a.split(" ").filter(Boolean).sort().join(" "), b.split(" ").filter(Boolean).sort().join(" "));',
'}',
'function encodeMonoWav12k(int16Samples, sampleRate) {',
'  const buffer = new ArrayBuffer(44 + int16Samples.length * 2), view = new DataView(buffer);',
'  const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };',
'  writeStr(0, "RIFF"); view.setUint32(4, 36 + int16Samples.length * 2, true); writeStr(8, "WAVE"); writeStr(12, "fmt ");',
'  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);',
'  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);',
'  writeStr(36, "data"); view.setUint32(40, int16Samples.length * 2, true);',
'  for (let i = 0, offset = 44; i < int16Samples.length; i++, offset += 2) view.setInt16(offset, int16Samples[i], true);',
'  return new Blob([buffer], { type: "audio/wav" });',
'}',
'function formatSrtTime(secFloat) {',
'  const ms = Math.round((secFloat - Math.floor(secFloat)) * 1000), sInt = Math.floor(secFloat);',
'  const hrs = Math.floor(sInt / 3600), mins = Math.floor((sInt % 3600) / 60), secs = sInt % 60;',
'  return String(hrs).padStart(2, "0") + ":" + String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0") + "," + String(ms).padStart(3, "0");',
'}',
'function buildSrt(orderedItems, scenes) {',
'  let curr = 0.0, idx = 1; const blocks = [];',
'  for (let i = 0; i < orderedItems.length; i++) {',
'    const it = orderedItems[i], dur = it.duration > 0.5 ? it.duration : 8.0;',
'    let txt = (it.matchedSceneIdx !== null && scenes[it.matchedSceneIdx]) ? scenes[it.matchedSceneIdx].spoken : "";',
'    if (!txt && it.transcript && !it.transcript.startsWith("(")) txt = it.transcript;',
'    if (txt) {',
'      const words = txt.split(/\\s+/);',
'      if (words.length > 9) {',
'        const mid = Math.floor(words.length / 2), half = dur / 2.0;',
'        blocks.push((idx++) + "\\n" + formatSrtTime(curr) + " --> " + formatSrtTime(curr + half - 0.08) + "\\n" + words.slice(0, mid).join(" ") + "\\n");',
'        blocks.push((idx++) + "\\n" + formatSrtTime(curr + half) + " --> " + formatSrtTime(curr + dur - 0.12) + "\\n" + words.slice(mid).join(" ") + "\\n");',
'      } else {',
'        blocks.push((idx++) + "\\n" + formatSrtTime(curr) + " --> " + formatSrtTime(curr + dur - 0.12) + "\\n" + txt + "\\n");',
'      }',
'    }',
'    curr += dur;',
'  }',
'  return blocks.join("\\n");',
'}',
'function assignClipsExclusivelyJS(clips, scenes, endKeywords, dropUnmatched, padMissingSlots) {',
'  const numScenes = scenes.length;',
'  if (!numScenes) {',
'    const kept = clips.filter(c => !dropUnmatched || !c.isMuted);',
'    kept.sort((a, b) => a.dateMs - b.dateMs || a.name.localeCompare(b.name, undefined, { numeric: true }));',
'    kept.forEach(c => { c.matchedSceneIdx = null; c.score = 100; });',
'    return { kept, discardedCount: clips.length - kept.length, missingScenes: [], paddedCount: 0 };',
'  }',
'  const sceneNorms = scenes.map(s => normalizeText(s.spoken || "")), wordFreq = {};',
'  const sceneWordSets = sceneNorms.map(sn => {',
'    const ws = new Set(sn.split(" ").filter(w => w.length >= 4));',
'    ws.forEach(w => { wordFreq[w] = (wordFreq[w] || 0) + 1; }); return ws;',
'  });',
'  const bestScorePerClip = new Float32Array(clips.length), bestScenePerClip = new Int32Array(clips.length).fill(-1), pairs = [];',
'  clips.forEach((clip, cIdx) => {',
'    clip.tNorm = normalizeText(clip.transcript || "");',
'    if (clip.isMuted || !clip.tNorm || clip.tNorm.length < 5) return;',
'    const tWords = new Set(clip.tNorm.split(" ").filter(w => w.length >= 4));',
'    const hasEndKw = endKeywords.some(kw => clip.tNorm.includes(kw));',
'    let maxSc = 0, maxIdx = -1;',
'    sceneNorms.forEach((sNorm, sIdx) => {',
'      if (!sNorm) return;',
'      let score = (levenshteinRatio(clip.tNorm, sNorm) * 0.62) + (tokenSortRatio(clip.tNorm, sNorm) * 0.38);',
'      let rareBonus = 0;',
'      tWords.forEach(w => { if (sceneWordSets[sIdx].has(w)) rareBonus += (wordFreq[w] === 1 ? 8.5 : (wordFreq[w] === 2 ? 3.5 : 0)); });',
'      score = Math.min(100, score + Math.min(22, rareBonus));',
'      if (hasEndKw && sIdx === numScenes - 1) score = Math.min(100, score + 18);',
'      else if (hasEndKw && sIdx < numScenes - 2) score -= 25;',
'      if (score > maxSc) { maxSc = score; maxIdx = sIdx; }',
'      pairs.push({ score, cIdx, sIdx });',
'    });',
'    bestScorePerClip[cIdx] = maxSc; bestScenePerClip[cIdx] = maxIdx;',
'  });',
'  pairs.sort((a, b) => b.score - a.score);',
'  const assigned = new Map(), sceneToClipMap = new Map(), acceptedClipsList = [];',
'  for (const p of pairs) {',
'    if (p.score < 50.0) break;',
'    if (assigned.has(p.cIdx) || sceneToClipMap.has(p.sIdx)) continue;',
'    if (p.sIdx !== bestScenePerClip[p.cIdx] && p.score < (bestScorePerClip[p.cIdx] - 7.5)) continue;',
'    const candNorm = clips[p.cIdx].tNorm; let isClone = false;',
'    for (const prev of acceptedClipsList) {',
'      if (Math.max(levenshteinRatio(candNorm, prev.tNorm), tokenSortRatio(candNorm, prev.tNorm)) >= 70.0) {',
'        if (levenshteinRatio(sceneNorms[p.sIdx], sceneNorms[prev.sIdx]) < 75.0) { isClone = true; break; }',
'      }',
'    }',
'    if (isClone) continue;',
'    assigned.set(p.cIdx, p); sceneToClipMap.set(p.sIdx, clips[p.cIdx]);',
'    acceptedClipsList.push({ cIdx: p.cIdx, sIdx: p.sIdx, tNorm: candNorm });',
'  }',
'  let discardedCount = 0;',
'  clips.forEach((clip, cIdx) => {',
'    if (assigned.has(cIdx)) {',
'      const m = assigned.get(cIdx); clip.position = m.sIdx; clip.matchedSceneIdx = m.sIdx; clip.score = Math.round(m.score * 10) / 10;',
'    } else { discardedCount++; }',
'  });',
'  const missingScenes = []; for (let i = 0; i < numScenes; i++) { if (!sceneToClipMap.has(i)) missingScenes.push(i + 1); }',
'  let kept = [], paddedCount = 0;',
'  if (padMissingSlots && sceneToClipMap.size > 0) {',
'    // TRAVA ANTI-DESLIZAMENTO DE AUDIO 2A: Mantem os 8s exatos de cada cena que faltou repetindo visual vizinho B-Roll!',
'    let lastValid = null;',
'    for (let i = 0; i < numScenes; i++) { if (sceneToClipMap.has(i)) { lastValid = sceneToClipMap.get(i); break; } }',
'    for (let i = 0; i < numScenes; i++) {',
'      if (sceneToClipMap.has(i)) {',
'        lastValid = sceneToClipMap.get(i); kept.push(lastValid);',
'      } else if (lastValid) {',
'        paddedCount++;',
'        kept.push({ name: "Preenchimento_Sincronia_Cena_" + (i + 1) + ".mp4", duration: 8.0, byteLength: lastValid.byteLength || 0, sizeHint: lastValid.sizeHint || 0, matchedSceneIdx: i, score: 0, transcript: "(Preenchimento automatico de sincronia)", getUint8: lastValid.getUint8 });',
'      }',
'    }',
'  } else {',
'    clips.forEach((clip, cIdx) => { if (assigned.has(cIdx)) kept.push(clip); else if (!dropUnmatched && !clip.isMuted) { clip.position = 99999 + cIdx; clip.matchedSceneIdx = null; clip.score = 0; kept.push(clip); } });',
'    kept.sort((a, b) => a.position - b.position || a.name.localeCompare(b.name, undefined, { numeric: true }));',
'  }',
'  return { kept, discardedCount, missingScenes, paddedCount };',
'}',
'let CACHED_CORE_BLOB_URL = null, CACHED_WASM_BLOB_URL = null;',
'async function fetchAsBlobUrl(url, mimeType) {',
'  const resp = await fetch(url); if (!resp.ok) throw new Error("HTTP " + resp.status);',
'  return URL.createObjectURL(new Blob([await resp.arrayBuffer()], { type: mimeType }));',
'}',
'async function createFreshFFmpegSingleThread() {',
'  if (!window.FFmpeg || !window.FFmpeg.createFFmpeg) throw new Error("FFmpeg CDN nao carregou.");',
'  if (!CACHED_CORE_BLOB_URL || !CACHED_WASM_BLOB_URL) {',
'    const cdns = ["https://cdn.jsdelivr.net/npm/@ffmpeg/core-st@0.11.1/dist", "https://unpkg.com/@ffmpeg/core-st@0.11.1/dist"];',
'    for (const base of cdns) {',
'      try {',
'        CACHED_CORE_BLOB_URL = await fetchAsBlobUrl(base + "/ffmpeg-core.js", "text/javascript");',
'        CACHED_WASM_BLOB_URL = await fetchAsBlobUrl(base + "/ffmpeg-core.wasm", "application/wasm"); break;',
'      } catch (e) {}',
'    }',
'  }',
'  const ffmpeg = window.FFmpeg.createFFmpeg({ mainName: "main", corePath: CACHED_CORE_BLOB_URL, wasmPath: CACHED_WASM_BLOB_URL, workerPath: CACHED_CORE_BLOB_URL, log: false });',
'  await ffmpeg.load(); return ffmpeg;',
'}',
'async function runFFmpegSafe(ffInstance, argsArray) {',
'  try { await ffInstance.run(...argsArray); } catch (err) {',
'    const msg = String((err && (err.message || err)) || "");',
'    if (msg.includes("exit(0)") || (err && err.status === 0)) return;',
'    throw err;',
'  }',
'}',
'function safeCloseFFmpeg(ff) { if (ff) { try { ff.exit(); } catch (e) {} } }',
'async function joinScenesIntoSingleMp4(clipsSlice, voiceFile, bgmFile, bgmVol, progStart, progSpan, labelPrefix) {',
'  const batchSize = 18, numBatches = Math.ceil(clipsSlice.length / batchSize), tsChunks = []; let totalTsBytes = 0;',
'  for (let b = 0; b < numBatches; b++) {',
'    const sub = clipsSlice.slice(b * batchSize, (b + 1) * batchSize);',
'    setProgress(progStart + ((b + 1) / numBatches) * (progSpan * 0.72), "⚡ " + labelPrefix + "Colando lote " + (b + 1) + "/" + numBatches + " (" + sub.length + " cenas)...");',
'    await yieldUI();',
'    let ffBatch = await createFreshFFmpegSingleThread();',
'    try {',
'      const concatLines = [];',
'      for (let k = 0; k < sub.length; k++) { const fn = "in_" + k + ".mp4"; ffBatch.FS("writeFile", fn, await sub[k].getUint8()); concatLines.push("file \'" + fn + "\'"); }',
'      ffBatch.FS("writeFile", "list.txt", new TextEncoder().encode(concatLines.join("\\n")));',
'      await runFFmpegSafe(ffBatch, ["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "mpegts", "batch.ts"]);',
'      const tsCopy = ffBatch.FS("readFile", "batch.ts").slice(); tsChunks.push(tsCopy); totalTsBytes += tsCopy.byteLength;',
'    } finally { safeCloseFFmpeg(ffBatch); }',
'  }',
'  setProgress(progStart + progSpan * 0.80, "🔗 " + labelPrefix + "Empacotando .MP4 continuo..."); await yieldUI();',
'  let mergedTs = new Uint8Array(totalTsBytes), offset = 0;',
'  for (let i = 0; i < tsChunks.length; i++) { mergedTs.set(tsChunks[i], offset); offset += tsChunks[i].byteLength; tsChunks[i] = null; }',
'  let ffMux = await createFreshFFmpegSingleThread(), finalBytes = null;',
'  try {',
'    ffMux.FS("writeFile", "all.ts", mergedTs); mergedTs = null;',
'    const muxArgs = totalTsBytes > 300 * 1048576 ? ["-i", "all.ts", "-c", "copy", "-bsf:a", "aac_adtstoasc", "joined.mp4"] : ["-i", "all.ts", "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", "joined.mp4"];',
'    await runFFmpegSafe(ffMux, muxArgs);',
'    if (!voiceFile && !bgmFile) return new Blob([ffMux.FS("readFile", "joined.mp4")], { type: "video/mp4" });',
'    finalBytes = ffMux.FS("readFile", "joined.mp4").slice();',
'  } finally { safeCloseFFmpeg(ffMux); }',
'  if (voiceFile) {',
'    setProgress(progStart + progSpan * 0.90, "🎙️ " + labelPrefix + "Sincronizando sua locucao principal completa..."); await yieldUI();',
'    let ffVoice = await createFreshFFmpegSingleThread();',
'    try {',
'      const vIn = "v." + (voiceFile.name.split(".").pop() || "mp3");',
'      ffVoice.FS("writeFile", "base.mp4", finalBytes); finalBytes = null;',
'      ffVoice.FS("writeFile", vIn, new Uint8Array(await voiceFile.arrayBuffer()));',
'      await runFFmpegSafe(ffVoice, ["-i", "base.mp4", "-i", vIn, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "voiced.mp4"]);',
'      if (!bgmFile) return new Blob([ffVoice.FS("readFile", "voiced.mp4")], { type: "video/mp4" });',
'      finalBytes = ffVoice.FS("readFile", "voiced.mp4").slice();',
'    } finally { safeCloseFFmpeg(ffVoice); }',
'  }',
'  if (bgmFile) {',
'    setProgress(progStart + progSpan * 0.95, "🎵 " + labelPrefix + "Mixando musica de fundo..."); await yieldUI();',
'    let ffBgm = await createFreshFFmpegSingleThread();',
'    try {',
'      const bIn = "b." + (bgmFile.name.split(".").pop() || "mp3");',
'      ffBgm.FS("writeFile", "base.mp4", finalBytes); finalBytes = null;',
'      ffBgm.FS("writeFile", bIn, new Uint8Array(await bgmFile.arrayBuffer()));',
'      await runFFmpegSafe(ffBgm, ["-i", "base.mp4", "-stream_loop", "-1", "-i", bIn, "-filter_complex", "[1:a]volume=" + bgmVol.toFixed(3) + "[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]", "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "bgm_out.mp4"]);',
'      return new Blob([ffBgm.FS("readFile", "bgm_out.mp4")], { type: "video/mp4" });',
'    } finally { safeCloseFFmpeg(ffBgm); }',
'  }',
'  return new Blob([finalBytes], { type: "video/mp4" });',
'}',
'async function transcribeBatchGroq(wavBlob, apiKey, langCode) {',
'  const sleep = ms => new Promise(r => setTimeout(r, ms));',
'  for (let attempt = 0; attempt < 5; attempt++) {',
'    const fd = new FormData(); fd.append("file", wavBlob, "batch.wav"); fd.append("model", "whisper-large-v3-turbo"); fd.append("language", langCode); fd.append("response_format", "verbose_json"); fd.append("timestamp_granularities[]", "word"); fd.append("timestamp_granularities[]", "segment");',
'    const resp = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", { method: "POST", headers: { "Authorization": "Bearer " + apiKey }, body: fd });',
'    if (resp.status === 200) return await resp.json();',
'    if (resp.status === 429) { logMsg("⏳ Pausa de 6s (limite gratuito Whisper)..."); await sleep(6000); continue; }',
'    throw new Error("Whisper HTTP " + resp.status);',
'  }',
'  throw new Error("Limite temporario Whisper.");',
'}',
'document.getElementById("btn-run").addEventListener("click", async () => {',
'  const rawFiles = [...document.getElementById("inp-videos").files];',
'  if (!rawFiles.length) { alert("Selecione primeiro o arquivo .ZIP ou os videos .MP4!"); return; }',
'  const activeScenes = getActiveScenes(), sortMode = document.getElementById("sel-sort").value;',
'  const dropMuted = document.getElementById("chk-drop-muted").checked, preferSingleFile = document.getElementById("chk-single-file").checked;',
'  const voiceFile = document.getElementById("inp-voice").files[0] || null, bgmFile = document.getElementById("inp-bgm").files[0] || null;',
'  const padMissing = document.getElementById("chk-pad-missing").checked && (voiceFile !== null);',
'  const bgmVol = parseInt(document.getElementById("inp-bgm-vol").value || "12", 10) / 100.0;',
'  const btn = document.getElementById("btn-run"); btn.disabled = true;',
'  document.getElementById("dl-box").style.display = "none"; document.getElementById("log-box").innerHTML = "";',
'  try {',
'    setProgress(3, "📂 Lendo pacote de videos na memoria do seu PC..."); await yieldUI();',
'    const clipEntries = [];',
'    for (const f of rawFiles) {',
'      if (f.name.toLowerCase().endsWith(".zip")) {',
'        const zip = await JSZip.loadAsync(f);',
'        for (const path of Object.keys(zip.files)) {',
'          const zObj = zip.files[path];',
'          if (!zObj.dir && path.toLowerCase().endsWith(".mp4") && !path.startsWith("__MACOSX")) {',
'            const baseName = path.split("/").pop();',
'            if (baseName && !baseName.startsWith("._")) clipEntries.push({ name: baseName, dateMs: zObj.date ? zObj.date.getTime() : 0, getUint8: async () => await zObj.async("uint8array"), sizeHint: zObj._data && zObj._data.uncompressedSize ? zObj._data.uncompressedSize : 0 });',
'          }',
'        }',
'      } else if (f.name.toLowerCase().endsWith(".mp4")) {',
'        clipEntries.push({ name: f.name, dateMs: f.lastModified || 0, getUint8: async () => new Uint8Array(await f.arrayBuffer()), sizeHint: f.size });',
'      }',
'    }',
'    if (!clipEntries.length) throw new Error("Nenhum .MP4 valido encontrado!");',
'    logMsg("✅ " + clipEntries.length + " clipes localizados!");',
'    const needAudioCheck = (dropMuted && sortMode !== "alpha") || (sortMode === "whisper");',
'    const sampleRateTarget = 12000, slotSeconds = 11, pcm12kPerClip = new Array(clipEntries.length).fill(null);',
'    if (needAudioCheck) {',
'      const AudioCtx = window.AudioContext || window.webkitAudioContext, actx = new AudioCtx();',
'      try {',
'        for (let i = 0; i < clipEntries.length; i++) {',
'          setProgress(5 + ((i + 1) / clipEntries.length) * 26, "🎧 Analisando clipe " + (i + 1) + "/" + clipEntries.length + "...");',
'          const bytes = await clipEntries[i].getUint8(); clipEntries[i].byteLength = bytes.byteLength;',
'          try {',
'            const abuf = await actx.decodeAudioData(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));',
'            clipEntries[i].duration = abuf.duration || 8.0; const ch0 = abuf.getChannelData(0);',
'            let sumSq = 0, countRms = 0; const stepRms = Math.max(1, Math.floor(ch0.length / 8000));',
'            for (let k = 0; k < ch0.length; k += stepRms) { sumSq += ch0[k] * ch0[k]; countRms++; }',
'            clipEntries[i].isMuted = (Math.sqrt(sumSq / Math.max(1, countRms)) < 0.0045);',
'            if (!clipEntries[i].isMuted && sortMode === "whisper") {',
'              const ratio = abuf.sampleRate / sampleRateTarget, maxSamples = Math.min(Math.floor(ch0.length / ratio), Math.floor(sampleRateTarget * 8.4));',
'              const down = new Int16Array(maxSamples);',
'              for (let s = 0; s < maxSamples; s++) { const v = Math.max(-1, Math.min(1, ch0[Math.floor(s * ratio)])); down[s] = v < 0 ? v * 0x8000 : v * 0x7FFF; }',
'              pcm12kPerClip[i] = down;',
'            }',
'          } catch (decErr) { clipEntries[i].duration = 8.0; clipEntries[i].isMuted = true; }',
'        }',
'      } finally { try { await actx.close(); } catch (e) {} }',
'    } else { clipEntries.forEach(c => { c.duration = 8.0; c.isMuted = false; }); }',
'    let orderedClips = [], discardedCount = 0, missingScenes = [], paddedCount = 0;',
'    const canUseWhisper = (sortMode === "whisper") && CONFIG.groqKey && CONFIG.groqKey.startsWith("gsk_") && activeScenes.length > 0;',
'    if (canUseWhisper) {',
'      const speakableIndices = []; clipEntries.forEach((c, idx) => { if (!c.isMuted && pcm12kPerClip[idx]) speakableIndices.push(idx); });',
'      const batchSize = 7, totalBatches = Math.ceil(speakableIndices.length / batchSize);',
'      for (let b = 0; b < totalBatches; b++) {',
'        const sliceIdxs = speakableIndices.slice(b * batchSize, (b + 1) * batchSize);',
'        setProgress(32 + ((b + 1) / Math.max(1, totalBatches)) * 24, "🧠 Pareando falas IA (Lote " + (b + 1) + "/" + totalBatches + ")...");',
'        const batchPcm = new Int16Array(sliceIdxs.length * slotSeconds * sampleRateTarget);',
'        sliceIdxs.forEach((origIdx, slotPos) => { batchPcm.set(pcm12kPerClip[origIdx], slotPos * slotSeconds * sampleRateTarget); pcm12kPerClip[origIdx] = null; });',
'        const wData = await transcribeBatchGroq(encodeMonoWav12k(batchPcm, sampleRateTarget), CONFIG.groqKey, CONFIG.whisperLang);',
'        const buckets = Array.from({ length: sliceIdxs.length }, () => []);',
'        if (wData.words && wData.words.length > 0) {',
'          for (const w of wData.words) { const sPos = Math.min(sliceIdxs.length - 1, Math.max(0, Math.floor(((w.start || 0) + 0.15) / slotSeconds))); buckets[sPos].push(w.word); }',
'        } else if (wData.segments && wData.segments.length > 0) {',
'          for (const seg of wData.segments) { const sPos = Math.min(sliceIdxs.length - 1, Math.max(0, Math.floor((((seg.start || 0) + (seg.end || 0)) / 2.0) / slotSeconds))); buckets[sPos].push(seg.text); }',
'        }',
'        sliceIdxs.forEach((origIdx, slotPos) => { clipEntries[origIdx].transcript = buckets[slotPos].join(" ").replace(/\\s+/g, " ").trim(); if (!clipEntries[origIdx].transcript) clipEntries[origIdx].isMuted = true; });',
'      }',
'      const matchRes = assignClipsExclusivelyJS(clipEntries, activeScenes, CONFIG.endKeywords, dropMuted, padMissing);',
'      orderedClips = matchRes.kept; discardedCount = matchRes.discardedCount; missingScenes = matchRes.missingScenes; paddedCount = matchRes.paddedCount;',
'      if (!orderedClips.length && clipEntries.length) { orderedClips = clipEntries.filter(c => !c.isMuted); if (!orderedClips.length) orderedClips = clipEntries; }',
'    } else if (sortMode === "chron_flow" || (sortMode === "whisper" && !canUseWhisper)) {',
'      orderedClips = clipEntries.filter(c => !dropMuted || !c.isMuted); discardedCount = clipEntries.length - orderedClips.length;',
'      orderedClips.sort((a, b) => (a.dateMs - b.dateMs) || a.name.localeCompare(b.name, undefined, { numeric: true }));',
'      orderedClips.forEach((c, idx) => { c.matchedSceneIdx = idx < activeScenes.length ? idx : null; c.transcript = "(Ordem do pacote)"; c.score = 100; });',
'    } else {',
'      orderedClips = [...clipEntries].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));',
'      orderedClips.forEach((c, idx) => { c.matchedSceneIdx = idx < activeScenes.length ? idx : null; c.transcript = "(Ordem alfabetica)"; c.score = 100; });',
'    }',
'    const totalSelectedMB = orderedClips.reduce((acc, c) => acc + (c.byteLength || c.sizeHint || 0), 0) / 1048576;',
'    if (paddedCount > 0) logMsg("🛡️ Anti-Deslizamento: " + paddedCount + " cena(s) faltante(s) preenchida(s) para manter 100% da sincronia com sua locucao 2A!");',
'    const partBlobs = []; let mustSplit = (!preferSingleFile && totalSelectedMB > 650) || (totalSelectedMB > 1250);',
'    if (!mustSplit) {',
'      try {',
'        const singleBlob = await joinScenesIntoSingleMp4(orderedClips, voiceFile, bgmFile, bgmVol, 58, 40, "");',
'        partBlobs.push({ name: "VIDEO_FINAL_LIMPO_COMPLETO.mp4", label: "💾 BAIXAR VÍDEO COMPLETO", blob: singleBlob });',
'      } catch (memErr) { mustSplit = true; }',
'    }',
'    if (mustSplit && partBlobs.length === 0) {',
'      const numParts = Math.max(2, Math.ceil(totalSelectedMB / 500)), perPart = Math.ceil(orderedClips.length / numParts);',
'      for (let p = 0; p < numParts; p++) {',
'        const sub = orderedClips.slice(p * perPart, (p + 1) * perPart), span = 40 / numParts;',
'        const pBlob = await joinScenesIntoSingleMp4(sub, null, bgmFile, bgmVol, 58 + p * span, span, "[Parte " + (p + 1) + "] ");',
'        partBlobs.push({ name: "VIDEO_FINAL_PARTE_" + (p + 1) + ".mp4", label: "💾 BAIXAR PARTE " + (p + 1), blob: pBlob });',
'      }',
'    }',
'    const srtUrl = URL.createObjectURL(new Blob([buildSrt(orderedClips, activeScenes)], { type: "text/plain;charset=utf-8" }));',
'    setProgress(100, "🎉 Vídeo pronto e sincronizado!");',
'    document.getElementById("dl-box").style.display = "block";',
'    const sumMB = partBlobs.reduce((acc, b) => acc + b.blob.size, 0) / 1048576;',
'    document.getElementById("dl-summary").innerText = "✅ MONTAGEM v3.3 CONCLUÍDA! " + orderedClips.length + " blocos (" + sumMB.toFixed(1) + " MB)" + (paddedCount > 0 ? " | 🛡️ " + paddedCount + " buraco(s) sincronizado(s)" : "");',
'    document.getElementById("dl-missing").innerText = missingScenes.length ? ("⚠️ Cenas não geradas no Flow: Cena(s) " + missingScenes.join(", ") + ".") : "";',
'    const btnContainer = document.getElementById("dl-buttons-container"); btnContainer.innerHTML = "";',
'    partBlobs.forEach(pb => {',
'      const a = document.createElement("a"); a.className = "dl-btn dl-mp4"; a.href = URL.createObjectURL(pb.blob); a.download = pb.name;',
'      a.innerText = pb.label + " (" + (pb.blob.size / 1048576).toFixed(1) + " MB .MP4)"; btnContainer.appendChild(a);',
'    });',
'    const aSrt = document.createElement("a"); aSrt.className = "dl-btn dl-srt"; aSrt.href = srtUrl; aSrt.download = "Legenda_Sincronizada.srt"; aSrt.innerText = "📝 BAIXAR LEGENDA (.SRT)"; btnContainer.appendChild(aSrt);',
'  } catch (err) {',
'    const msg = (err && (err.message || String(err))) || "Use Abrir em Aba Dedicada (+RAM)!";',
'    setProgress(0, "❌ Erro: " + msg); logMsg("ERRO: " + msg);',
'  } finally { btn.disabled = false; }',
'});',
'</script></body></html>'
]

def render_ffmpeg_wasm_assembler(raw_script, lang_label, groq_api_key, is_vertical, preserve_1to1=False):
    scenes_parsed = extract_scenes_for_prompts(raw_script, lang_label, preserve_1to1_blocks=preserve_1to1)
    js_scenes = [{"spoken": sc.get("spoken", "")} for sc in scenes_parsed if sc.get("spoken")]
    cfg = {
        "rawScript": raw_script or "",
        "scenes": js_scenes,
        "groqKey": groq_api_key if (groq_api_key and groq_api_key.startswith("gsk_")) else "",
        "whisperLang": LANGUAGES[lang_label]["whisper_code"],
        "endKeywords": LANGUAGES[lang_label]["end_keywords"],
        "isVertical": is_vertical,
        "preserve1to1": preserve_1to1
    }
    safe_json = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    html_out = "\n".join(FFMPEG_WASM_HTML_LINES).replace("__CONFIG_JSON__", safe_json)
    components.html(html_out, height=840, scrolling=True)
# ===============================================================================================

# ================= TOPO DO ESTÚDIO & VÍDEO TUTORIAL =================
is_admin = (st.session_state.get("user_role") == "admin")
col_hdr1, col_hdr2 = st.columns([5, 1])
with col_hdr1:
    st.title("🎬 Estúdio Pro Ultimate — Vídeos 16:9 & 9:16, FFmpeg.wasm v3.3 & SEO")
with col_hdr2:
    st.caption(f"👤 `{st.session_state.get('user_email', '')}`")
    if st.button("🔒 Sair", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

with st.expander("▶️ PASSO A PASSO RÁPIDO: Qual Modo escolher (Narrador, Diálogo ou Seu Próprio Áudio)"):
    st.markdown(
        "* **🎙️ Modo 1 (Narrador Fixo):** Ideal para histórias bíblicas, documentários de cidades e curiosidades (B-Roll puro sem apresentadores aleatórios!).\n"
        "* **🗣️ Modo 2 (Diálogo Entre Personagens):** Para 2 personagens conversando com Lip-Sync.\n"
        "* **🎧 Modo 3 (Seu Próprio Áudio):** Suba seu `.MP3/.WAV` gravado — fatia de 8 em 8s com trava 1-para-1 e protege a sincronia mesmo se faltar cena no Flow!\n"
        "* **💡 No Google Flow:** Envie pela **Extensão VIP v2.0** (ou de 5 em 5 cenas no chat lateral) para evitar pausas por alta demanda."
    )

col_top1, col_top2, col_top3 = st.columns([1.1, 1.1, 1.6])
with col_top1:
    selected_lang = st.selectbox("🌍 Idioma do Projeto:", list(LANGUAGES.keys()))
with col_top2:
    aspect_ratio = st.selectbox(
        "📐 Formato da Tela:",
        ["🖥️ 16:9 Horizontal (YouTube Longo)", "📱 9:16 Vertical (TikTok / Shorts / Reels)"]
    )
    is_vertical = ("9:16" in aspect_ratio)
    aspect_short = "Vertical 9:16 portrait video" if is_vertical else "Horizontal 16:9 widescreen video"

with col_top3:
    if is_admin:
        admin_secret_key = ""
        try:
            admin_secret_key = str(st.secrets.get("API_KEY", "") or st.secrets.get("GEMINI_API_KEY", "")).strip()
        except Exception:
            admin_secret_key = ""
        override_key = st.text_input(
            "🔑 Modo Admin (Sua chave oculta já está ativa — ou cole outra):",
            value="",
            type="password",
            placeholder="Usando sua API_KEY oculta automaticamente"
        )
        active_api_key = override_key.strip() if override_key.strip() else admin_secret_key
    else:
        active_api_key = st.text_input(
            "🔑 Sua Chave Gratuita Groq ('gsk_...' — cole e aperte ENTER):",
            value="",
            type="password",
            placeholder="Pegue grátis em console.groq.com/keys"
        ).strip()

tab1, tab2, tab3 = st.tabs([
    "📝 1. Personagens, Roteiro & Prompts",
    "⚡ 2. Montagem Local FFmpeg.wasm v3.3 (Sincronia Cravada)",
    "🚀 3. Kit Publicação Viral (Títulos, SEO & Capa)"
])

with tab1:
    cf_btn1, cf_btn2 = st.columns([1, 1])
    with cf_btn1:
        components.html(
            '<button onclick="window.open(\'https://labs.google/fx/pt/tools/flow\',\'FlowPopup\',\'width=980,height=860,left=920,top=60\');" '
            'style="width:100%;padding:10px 14px;background:#1d4ed8;color:white;border:none;border-radius:8px;font-weight:600;font-family:sans-serif;cursor:pointer;font-size:14px;">'
            '⚡ Abrir Google Flow em Janela Lateral (Login Seguro)</button>',
            height=48
        )
    with cf_btn2:
        st.download_button(
            "🧩 Baixar Extensão Chrome VIP v2.0 (Linha Única — Evita Limite de Alta Demanda)",
            data=build_chrome_extension_zip(),
            file_name="Extensao_VIP_Estudio_Pro_Flow_v2.zip",
            mime="application/zip",
            use_container_width=True
        )

    st.markdown("### 🎛️ Passo 1: Modo de Áudio e Upload dos Personagens")
    audio_mode = st.radio(
        "Como será o áudio e a atuação deste vídeo?",
        [
            "🎙️ Modo 1: Narrador Fixo (Ideal p/ Histórias Bíblicas, Documentários e Contos — B-Roll Puro)",
            "🗣️ Modo 2: Diálogo Entre Personagens (2 Personagens Conversando com Lip-Sync)",
            "🎧 Modo 3: Usar Meu Próprio Áudio Gravado (.MP3 / .WAV — Sincronia 1:1 de 8 em 8s + Anti-Deslizamento)"
        ]
    )

    voice_choice = "🎙️ Voz Masculina Fixa (Barítono 35 anos)"
    custom_voice_timbre = ""
    mute_flow_for_custom = False
    has_ref_image = False

    if "Modo 1" in audio_mode or "Modo 3" in audio_mode:
        cm1, cm2 = st.columns([1, 1])
        with cm1:
            if "Modo 1" in audio_mode:
                voice_choice = st.radio("Gênero da Voz Fixa:", ["🎙️ Voz Masculina Fixa (Barítono 35 anos)", "🎙️ Voz Feminina Fixa (Mezzo-Soprano 32 anos)"])
                custom_voice_timbre = st.text_input("Assinatura extra de voz (Opcional):", placeholder="Ex: Sotaque mineiro acolhedor, ritmo calmo")
            else:
                ref_audio_file = st.file_uploader("🎵 Suba seu áudio gravado (.mp3, .wav, .m4a) para fatiar de 8 em 8s:", type=["mp3", "wav", "m4a", "ogg"])
                mute_flow_for_custom = st.checkbox("Gerar vídeos mudos no Flow (Recomendado deixar DESMARCADO para alinhamento automático!)", value=False)
                if ref_audio_file is not None:
                    if st.button("🎧 LER MEU ÁUDIO E MONTAR ROTEIRO SINCRONIZADO (8 EM 8s)", type="primary", use_container_width=True):
                        with st.spinner("Transcrevendo seu áudio em janelas cravadas de 8.0 segundos (Whisper Turbo)..."):
                            ffmpeg_exe = get_ffmpeg()
                            tmp_dir_a = tempfile.mkdtemp()
                            try:
                                tmp_aud = os.path.join(tmp_dir_a, ref_audio_file.name)
                                with open(tmp_aud, "wb") as fa:
                                    fa.write(ref_audio_file.getbuffer())
                                t_script, dur_s, n_sc = transcribe_uploaded_audio_chunks(
                                    tmp_aud, LANGUAGES[selected_lang]["sr_code"], LANGUAGES[selected_lang]["whisper_code"], active_api_key, ffmpeg_exe
                                )
                                st.session_state["saved_script"] = t_script
                                st.session_state["custom_audio_1to1_lock"] = True
                                st.session_state["auto_duration_min"] = max(1, math.ceil(dur_s / 60.0))
                                st.success(f"✅ Áudio transcrito ({dur_s:.1f}s ➔ {n_sc} cenas exatas de 8s)! Agora clique no botão azul lá embaixo.")
                            finally:
                                shutil.rmtree(tmp_dir_a, ignore_errors=True)
        with cm2:
            up_single = st.file_uploader("📸 Opcional: Subir Foto do Personagem ou Produto Fixo:", type=["png", "jpg", "jpeg", "webp"], key="up_single")
            if up_single is not None:
                has_ref_image = True
                st.image(up_single, width=140, caption="Referência Visual")
                if st.button("🔍 EXTRAIR DNA FÍSICO DA FOTO (IA)", key="btn_single_dna", use_container_width=True):
                    with st.spinner("Analisando cada detalhe na foto..."):
                        dna_res, err_v = analyze_character_photo(up_single, active_api_key)
                        if err_v:
                            st.error(err_v)
                        else:
                            st.session_state["_pending_cast_sync"] = {"dna_single_char": dna_res}
                            st.rerun()
            st.text_area("🧬 DNA Físico Fixo do Protagonista (Deixe vazio para Documentários de Cidades!):", key="dna_single_char", height=90)

    elif "Modo 2" in audio_mode:
        orient_label = "9:16" if is_vertical else "16:9"
        st.info(f"💡 **Modo Diálogo Inteligente ({orient_label}):** Suba fotos OU digite o tema no Passo 2 para adaptação automática de época.")
        up_col1, up_col2 = st.columns([1, 1])
        with up_col1:
            up_char_a = st.file_uploader("📸 Subir Foto do Personagem A (Opcional):", type=["png", "jpg", "jpeg", "webp"], key="up_a")
            if up_char_a is not None:
                has_ref_image = True
                st.image(up_char_a, width=140)
        with up_col2:
            up_char_b = st.file_uploader("📸 Subir Foto do Personagem B (Opcional):", type=["png", "jpg", "jpeg", "webp"], key="up_b")
            if up_char_b is not None:
                has_ref_image = True
                st.image(up_char_b, width=140)

        if up_char_a is not None or up_char_b is not None:
            b_col1, b_col2 = st.columns([1, 1])
            with b_col1:
                if st.button("🔍 EXTRAIR DNA FÍSICO E ROUPAS DAS FOTOS (IA)", type="primary", use_container_width=True):
                    sync_d = {}
                    if up_char_a is not None:
                        dna_a, err_a = analyze_character_photo(up_char_a, active_api_key)
                        if not err_a:
                            sync_d["dna_char_a"] = dna_a
                    if up_char_b is not None:
                        dna_b, err_b = analyze_character_photo(up_char_b, active_api_key)
                        if not err_b:
                            sync_d["dna_char_b"] = dna_b
                    if sync_d:
                        st.session_state["_pending_cast_sync"] = sync_d
                        st.rerun()
            with b_col2:
                duo_png = build_duo_reference_card(up_char_a, up_char_b, is_vertical=is_vertical)
                if duo_png:
                    st.download_button(f"🖼️ Baixar Cartão {orient_label}", data=duo_png, file_name="Referencia_Flow.png", mime="image/png", use_container_width=True)

        cd1, cd2 = st.columns([1, 1])
        with cd1:
            st.text_area("👤 DNA Físico e Roupa Fixa — Personagem A:", key="dna_char_a", height=95)
            st.text_input("🎙️ Trava de Voz — Personagem A:", key="voice_char_a")
        with cd2:
            st.text_area("👤 DNA Físico e Roupa Fixa — Personagem B:", key="dna_char_b", height=95)
            st.text_input("🎙️ Trava de Voz — Personagem B:", key="voice_char_b")

    st.divider()
    st.markdown("### 🤖 Passo 2: Gerar Roteiro pela IA ou Colar Qualquer Roteiro / Texto Puro")
    col_t1, col_t2, col_t3 = st.columns([3, 1, 1])
    with col_t1:
        video_title = st.text_input("Título ou Tema Geral do Vídeo:", placeholder="Ex: A História de Davi e Golias / Juiz de Fora vs Uberlândia")
    with col_t2:
        duration_min = st.number_input("Duração (Minutos):", min_value=1, max_value=15, value=st.session_state["auto_duration_min"], step=1)
    with col_t3:
        total_scenes_calc = max(4, int((duration_min * 60) // 8))
        st.metric("Total de Cenas (8s)", f"{total_scenes_calc} cenas")

    cs1, cs2 = st.columns([1, 1])
    with cs1:
        style_choice = st.selectbox("Estilo Visual Fixo:", list(STYLE_PRESETS.keys()))
        custom_style = st.text_input("Descreva o estilo visual personalizado:") if style_choice == "Personalizado (Definir abaixo)" else ""

        if st.button("🪄 CRIAR ROTEIRO COMPLETO PELA IA", use_container_width=True):
            if not video_title.strip():
                st.warning("Digite o tema ou situação primeiro.")
            else:
                st.session_state["custom_audio_1to1_lock"] = False
                eff_a = st.session_state.get("dna_char_a", "").strip()
                eff_b = st.session_state.get("dna_char_b", "").strip()
                if "Modo 2" in audio_mode and not has_ref_image and (not eff_a or not eff_b or (eff_a == DEFAULT_CHAR_A and eff_b == DEFAULT_CHAR_B)):
                    with st.spinner(f"🎭 Adaptando personagens para '{video_title}'..."):
                        adapted = auto_adapt_dialogue_cast(video_title.strip(), style_choice, active_api_key)
                        if adapted:
                            eff_a, eff_b = adapted["DNA_A"], adapted["DNA_B"]
                            st.session_state["_pending_cast_sync"] = {
                                "dna_char_a": eff_a, "dna_char_b": eff_b,
                                "voice_char_a": adapted.get("VOICE_A", DEFAULT_VOICE_A),
                                "voice_char_b": adapted.get("VOICE_B", DEFAULT_VOICE_B)
                            }
                with st.spinner(f"Criando roteiro linear ({total_scenes_calc} cenas)..."):
                    script_out, err_msg = generate_ai_script(
                        video_title, total_scenes_calc, selected_lang, style_choice, audio_mode, aspect_short,
                        eff_a, eff_b, st.session_state.get("dna_single_char", ""), active_api_key
                    )
                    if err_msg:
                        st.error(err_msg)
                    else:
                        st.session_state["saved_script"] = script_out
                        st.rerun()

        auto_director_enabled = st.checkbox("🎬 Diretor Visual B-Roll Puro + Auto-DNA de Elenco", value=True)
        lock_1to1_mode = st.checkbox(
            "🔒 Trava 1-para-1 de Blocos (Mantém 1 cena de 8s por bloco — Ideal p/ Áudio Próprio)",
            value=("Modo 3" in audio_mode or st.session_state.get("custom_audio_1to1_lock", False))
        )

    with cs2:
        script_for_prompts = st.text_area(
            "Roteiro ou Texto Puro:",
            value=st.session_state["saved_script"],
            height=275
        )

    if st.button("✨ FATIAR EM 8s, TRAVAR ELENCO & GERAR PROMPTS EM LINHA ÚNICA", type="primary", use_container_width=True):
        if not script_for_prompts.strip():
            st.warning("Gere ou cole um roteiro/texto primeiro.")
        else:
            st.session_state["saved_script"] = script_for_prompts
            is_silent_custom = ("Modo 3" in audio_mode and mute_flow_for_custom)
            scenes = extract_scenes_for_prompts(
                script_for_prompts, selected_lang, preserve_1to1_blocks=lock_1to1_mode, allow_empty_speech=is_silent_custom
            )

            eff_dna_a = st.session_state.get("dna_char_a", "").strip()
            eff_dna_b = st.session_state.get("dna_char_b", "").strip()
            eff_voice_a = st.session_state.get("voice_char_a", "").strip()
            eff_voice_b = st.session_state.get("voice_char_b", "").strip()

            if "Modo 2" in audio_mode and video_title.strip() and active_api_key:
                if not eff_dna_a or not eff_dna_b or (not has_ref_image and eff_dna_a == DEFAULT_CHAR_A and eff_dna_b == DEFAULT_CHAR_B):
                    with st.spinner(f"🎭 Preenchendo aparência fiel à época para '{video_title}'..."):
                        adapted = auto_adapt_dialogue_cast(video_title.strip(), style_choice, active_api_key)
                        if adapted:
                            eff_dna_a, eff_dna_b = adapted["DNA_A"], adapted["DNA_B"]
                            eff_voice_a = adapted.get("VOICE_A", eff_voice_a)
                            eff_voice_b = adapted.get("VOICE_B", eff_voice_b)
                            st.session_state["_pending_cast_sync"] = {
                                "dna_char_a": eff_dna_a, "dna_char_b": eff_dna_b,
                                "voice_char_a": eff_voice_a, "voice_char_b": eff_voice_b
                            }

            effective_char_lock = st.session_state.get("dna_single_char", "").strip()
            if not effective_char_lock and "Modo 2" not in audio_mode and auto_director_enabled and active_api_key:
                with st.spinner("🧬 Verificando trava de personagens..."):
                    auto_cast = generate_auto_cast_dna(video_title.strip(), script_for_prompts, style_choice, active_api_key)
                    st.session_state["auto_cast_dna"] = auto_cast
                    effective_char_lock = auto_cast

            if effective_char_lock and "Modo 2" not in audio_mode:
                st.info(f"🧬 **Trava Automática de Aparência Ativada:** `{effective_char_lock}`")

            if auto_director_enabled and any(sc.get("needs_ai_visual") for sc in scenes):
                prog_dir = st.empty()
                scenes = enrich_scenes_with_ai_visuals(
                    scenes, video_title.strip(), style_choice, audio_mode, effective_char_lock, active_api_key, progress_placeholder=prog_dir
                )
            else:
                for sc in scenes:
                    if not sc.get("visual"):
                        sc["visual"] = "Cinematic 4K B-roll footage matching the narrated topic, zero text, zero presenters on screen"

            visual_anchor = custom_style if style_choice == "Personalizado (Definir abaixo)" else STYLE_PRESETS[style_choice]
            lang_en_name = LANGUAGES[selected_lang]["name_en"]
            ref_tag = "Match uploaded reference character image(s). " if has_ref_image else ""
            is_broll_doc = ("Modo 2" not in audio_mode and not effective_char_lock and "Realista" in style_choice)

            est_mins = round((len(scenes) * 8) / 60.0, 1)
            st.success(f"✅ {len(scenes)} Cenas em Linha Única prontas (~{est_mins} min) — Modo B-Roll Puro Ativo!")
            all_prompts_text = []

            for idx, sc in enumerate(scenes, 1):
                clean_spoken = fix_pronunciation(sc["spoken"].replace('"', "'").strip(), selected_lang)
                safe_vis = sanitize_visual_for_veo_safety(sc["visual"], is_narration_broll=is_broll_doc)

                if "Modo 2" in audio_mode:
                    is_a = (sc["speaker"] != "B")
                    active_char = "Character A" if is_a else "Character B"
                    silent_char = "Character B" if is_a else "Character A"
                    active_voice = (eff_voice_a if is_a else eff_voice_b) or "expressive native voice"
                    cast_prefix = (f"Character A: {eff_dna_a}. " if eff_dna_a else "") + (f"Character B: {eff_dna_b}. " if eff_dna_b else "")
                    raw_p = (
                        f"{aspect_short}. {visual_anchor} {ref_tag}{cast_prefix}"
                        f"Scene action: {safe_vis}. ONLY {active_char} moves mouth with natural lip-sync while {silent_char} listens silently. "
                        f"AUDIO RULE (MANDATORY AUDIBLE SPEECH IN {lang_en_name}, ZERO SILENT VIDEO, ZERO ENGLISH, zero music): "
                        f"{active_char} ({active_voice}) speaks clearly in native {lang_en_name}: \"{clean_spoken}\""
                    )
                elif is_silent_custom:
                    char_clause = f"Character Appearance Lock: {effective_char_lock}. " if effective_char_lock else ""
                    raw_p = (
                        f"{aspect_short}. {visual_anchor} {ref_tag}{char_clause}"
                        f"Scene action: {safe_vis}. Nobody speaks to camera. "
                        f"AUDIO RULE: Silent ambient sound only, zero speech, zero narration, zero music."
                    )
                else:
                    char_clause = f"Character Appearance Lock (NEVER alter hair or outfit): {effective_char_lock}. " if effective_char_lock else "Pure scenic B-roll (NO TV presenter, NO person talking to camera). "
                    voice_short = get_compact_voice_profile(voice_choice, custom_voice_timbre)
                    raw_p = (
                        f"{aspect_short}. {visual_anchor} {ref_tag}{char_clause}"
                        f"Scene action: {safe_vis}. Nobody on screen speaks to camera (off-screen studio narration only). "
                        f"VOICE & LANGUAGE LOCK (MANDATORY AUDIBLE VOICEOVER IN {lang_en_name}, NEVER MUTE, ZERO EXTRA WORDS, ZERO ENGLISH, zero music): "
                        f"{voice_short} speaks ONLY this exact line in native {lang_en_name}: \"{clean_spoken}\""
                    )

                p_box = re.sub(r'\s+', ' ', re.sub(r'[\r\n]+', ' ', raw_p)).strip()
                all_prompts_text.append(f"=== CENA {idx:03d} ===\n{p_box}\n")
                with st.expander(f"🎬 Cena {idx:03d} ({len(clean_spoken.split())} palavras) — \"{clean_spoken[:65]}...\"", expanded=(idx <= 3)):
                    st.code(p_box, language="text")

            full_txt_joined = "\n".join(all_prompts_text)
            st.download_button("📥 Baixar Todos os Prompts (.TXT)", data=full_txt_joined, file_name="Prompts_Flow.txt", use_container_width=True)
            with st.expander("📋 Ou copie todos os prompts de uma vez para colar na Extensão VIP v2.0"):
                st.code(full_txt_joined, language="text")

with tab2:
    st.subheader(f"Montagem Local FFmpeg.wasm v3.3 ({'9:16 Vertical' if is_vertical else '16:9 Horizontal'})")
    is_1to1_active = bool(st.session_state.get("custom_audio_1to1_lock", False))
    render_ffmpeg_wasm_assembler(st.session_state.get("saved_script", ""), selected_lang, active_api_key, is_vertical, preserve_1to1=is_1to1_active)

with tab3:
    st.subheader("🚀 Kit Completo de Publicação Viral (Títulos, Descrição SEO, Tags & Capa)")
    seo_topic = st.text_input("Tema ou Título Base do Projeto:", value=video_title if 'video_title' in locals() else "")
    seo_script_ref = st.text_area("Roteiro de Referência:", value=st.session_state.get("saved_script", ""), height=180)

    if st.button("✨ GERAR TÍTULOS VIRAIS, DESCRIÇÃO COM CAPÍTULOS, TAGS E PROMPT DE CAPA", type="primary", use_container_width=True):
        if not seo_topic.strip() and not seo_script_ref.strip():
            st.warning("Gere um roteiro na Aba 1 ou digite o tema acima primeiro.")
        else:
            with st.spinner("Criando estratégia de alto CTR, SEO e prompt da capa..."):
                combined_dna = (
                    f"Char A: {st.session_state.get('dna_char_a', '')} | Char B: {st.session_state.get('dna_char_b', '')}"
                    if "Modo 2" in audio_mode else (st.session_state.get("dna_single_char", "") or st.session_state.get("auto_cast_dna", "Cinematic B-roll"))
                )
                kit_txt, err_seo = generate_seo_and_thumbnail_kit(
                    seo_topic, seo_script_ref, selected_lang, aspect_ratio, style_choice, combined_dna, active_api_key
                )
                if err_seo:
                    st.error(err_seo)
                else:
                    st.session_state["seo_kit_output"] = kit_txt
                    st.success("✅ Kit de publicação gerado com sucesso!")

    if st.session_state.get("seo_kit_output"):
        st.markdown("---")
        st.markdown(st.session_state["seo_kit_output"])
        st.download_button(
            "📥 Baixar Kit Completo de Publicação (.TXT)",
            data=st.session_state["seo_kit_output"],
            file_name="Kit_Publicacao_SEO_Thumbnail.txt",
            use_container_width=True
        )
# FIM DO ARQUIVO SAAS ULTIMATE v3.3 COMPLETO
