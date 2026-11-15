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

# Aplica sincronizações pendentes ANTES de instanciar qualquer widget
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
        "Photorealistic 4K documentary B-roll cinema footage, natural lighting, authentic local geography and climate, single continuous camera shot, strictly ZERO on-screen text, ZERO signs/scoreboards, ZERO TV presenters."
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
  panel.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <strong style="font-size:14px;color:#34d399;">🎬 Estúdio Pro — Auto Flow v2.0</strong>
      <button id="ep-min-btn" style="background:none;border:none;color:#9ca3af;cursor:pointer;font-size:16px;">—</button>
    </div>
    <div id="ep-body">
      <div style="margin-bottom:6px;color:#d1d5db;font-size:12px;">Cole abaixo o conteúdo de <b>Prompts_Flow.txt</b>:</div>
      <textarea id="ep-prompts" rows="5" placeholder="=== CENA 001 ===..." style="width:100%;box-sizing:border-box;background:#1f2937;color:#fff;border:1px solid #4b5563;border-radius:8px;padding:8px;font-size:12px;"></textarea>
      <div style="display:flex;justify-content:space-between;align-items:center;margin:8px 0;">
        <label style="font-size:12px;color:#d1d5db;">⏱️ Pausa entre cenas (seg):</label>
        <input id="ep-delay" type="number" min="6" max="120" value="16" style="width:60px;background:#1f2937;color:#fff;border:1px solid #4b5563;border-radius:6px;padding:4px;text-align:center;"/>
      </div>
      <div style="display:flex;gap:8px;margin-top:8px;">
        <button id="ep-start" style="flex:1;background:#059669;color:#fff;border:none;border-radius:8px;padding:9px;font-weight:600;cursor:pointer;">🚀 Iniciar Fila v2.0</button>
        <button id="ep-stop" style="background:#dc2626;color:#fff;border:none;border-radius:8px;padding:9px 12px;font-weight:600;cursor:pointer;display:none;">⏹ Parar</button>
      </div>
      <div id="ep-status" style="margin-top:8px;font-size:12px;color:#93c5fd;min-height:18px;">Pronto (Modo Linha Única Anti-Corte).</div>
    </div>`;
  document.body.appendChild(panel);
  const bodyDiv = document.getElementById("ep-body");
  document.getElementById("ep-min-btn").onclick = () => { bodyDiv.style.display = bodyDiv.style.display === "none" ? "block" : "none"; };

  function parseScenes(raw) {
    if (!raw || !raw.trim()) return [];
    const p = raw.split(/===\s*CENA\s*\d+\s*===/i)
      .map(s => s.replace(/[\r\n]+/g, " ").replace(/\s+/g, " ").trim())
      .filter(Boolean);
    return p.length > 0 ? p : [raw.replace(/[\r\n]+/g, " ").replace(/\s+/g, " ").trim()];
  }

  function findFlowInput() {
    const els = [...document.querySelectorAll("textarea"), ...document.querySelectorAll('[contenteditable="true"]'), ...document.querySelectorAll('[role="textbox"]')];
    for (const el of els) {
      if (el.id === "ep-prompts") continue;
      const r = el.getBoundingClientRect();
      if (r.width > 160 && r.height > 24) return el;
    }
    return null;
  }

  function setSingleLineText(el, cleanText) {
    el.focus();
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) setter.call(el, ""); else el.value = "";
      el.dispatchEvent(new Event("input", { bubbles: true }));
      if (setter) setter.call(el, cleanText); else el.value = cleanText;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      document.execCommand("selectAll", false, null);
      document.execCommand("delete", false, null);
      document.execCommand("insertText", false, cleanText);
      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: cleanText }));
    }
  }

  function triggerSubmit(inputEl) {
    const btn = [...document.querySelectorAll("button")].find(b => {
      if (b.id.startsWith("ep-") || b.disabled) return false;
      const lb = ((b.innerText || "") + " " + (b.getAttribute("aria-label") || "") + " " + (b.textContent || "")).toLowerCase();
      return lb.includes("generate") || lb.includes("gerar") || lb.includes("create") || lb.includes("criar") || lb.includes("arrow_upward") || b.getAttribute("type") === "submit";
    });
    if (btn) { btn.click(); return; }
    inputEl.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
  }

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  document.getElementById("ep-stop").onclick = () => { stopRequested = true; };
  document.getElementById("ep-start").onclick = async () => {
    if (isRunning) return;
    const scenes = parseScenes(document.getElementById("ep-prompts").value);
    const delaySec = Math.max(6, parseInt(document.getElementById("ep-delay").value || "16", 10));
    const statusEl = document.getElementById("ep-status");
    if (!scenes.length) { statusEl.innerText = "⚠️ Cole os prompts primeiro!"; return; }
    if (!findFlowInput()) { statusEl.innerText = "⚠️ Abra um projeto do Flow onde aparece a caixa de prompt!"; return; }
    isRunning = true; stopRequested = false;
    document.getElementById("ep-start").style.display = "none";
    document.getElementById("ep-stop").style.display = "inline-block";
    for (let i = 0; i < scenes.length; i++) {
      if (stopRequested) break;
      const box = findFlowInput();
      if (!box) { await sleep(4000); i--; continue; }
      statusEl.innerText = `🎬 Preenchendo cena ${i + 1}/${scenes.length} completa...`;
      setSingleLineText(box, scenes[i]);
      await sleep(1400);
      triggerSubmit(box);
      if (i < scenes.length - 1 && !stopRequested) {
        for (let s = delaySec; s > 0; s--) {
          if (stopRequested) break;
          statusEl.innerText = `✅ Cena ${i + 1}/${scenes.length} enviada! Próxima em ${s}s...`;
          await sleep(1000);
        }
      }
    }
    isRunning = false;
    document.getElementById("ep-start").style.display = "inline-block";
    document.getElementById("ep-stop").style.display = "none";
    statusEl.innerText = stopRequested ? "⏹ Fila pausada." : `🎉 Todas as ${scenes.length} cenas enviadas!`;
  };
})();"""
    readme_str = (
        "COMO ATUALIZAR PARA A EXTENSÃO VIP v2.0 NO CHROME:\n"
        "1. Extraia este .ZIP numa pasta nova no seu computador.\n"
        "2. Abra chrome://extensions no navegador e REMOVA a versão antiga.\n"
        "3. Clique em 'Carregar sem compactação' e selecione a nova pasta extraída.\n"
        "4. Recarregue a página do Google Flow (F5) — o painel mostrará 'Auto Flow v2.0' em verde!\n"
        "IMPORTANTE NO GOOGLE FLOW: Use o modelo Veo 3 (com áudio ativo), configure 1 vídeo por prompt (evita takes repetidos) e deixe a varinha de 'Expandir/Reescrever comando' DESATIVADA."
    )
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Extensao_Estudio_Pro_Flow_v2/manifest.json", manifest_str)
        zf.writestr("Extensao_Estudio_Pro_Flow_v2/content.js", content_js_str)
        zf.writestr("Extensao_Estudio_Pro_Flow_v2/COMO_INSTALAR.txt", readme_str)
    return mem_zip.getvalue()

def sanitize_visual_for_veo_safety(vis_en, is_narration_broll=False):
    """Remove gatilhos de bloqueio e elimina âncoras de TV, neve no Brasil, placares falhados e botões YouTube."""
    if not vis_en:
        return ""
    s = vis_en
    s = re.sub(r'\bPixar[-\s]*style\b', '3D stylized animated', s, flags=re.IGNORECASE)
    s = re.sub(r'\bDisney\b', 'animated', s, flags=re.IGNORECASE)
    s = re.sub(r'\b(?:dead|corpse|bloody|bleeding|kills|killing)\b', 'defeated', s, flags=re.IGNORECASE)
    s = re.sub(r'\blies motionless\b', 'kneels defeated on the ground', s, flags=re.IGNORECASE)
    if is_narration_broll:
        # Impede neve em cidades brasileiras, apresentadores de TV, joinha e placas com texto errado!
        s = re.sub(r'\b(?:snow|snowy|snowfall|blizzard|frost|icy|freezing snow)\b', 'cool misty mountain morning', s, flags=re.IGNORECASE)
        s = re.sub(
            r'\b(?:presenter|host|anchor|newsreader|youtuber|influencer|man speaking to camera|person speaking|thumbs up|subscribe button|scoreboard|whiteboard|map with labels|split screen)\b',
            'scenic aerial panoramic drone view',
            s,
            flags=re.IGNORECASE
        )
    return re.sub(r'\s+', ' ', s).strip()

def fix_pronunciation(text, lang_label):
    if not text:
        return ""
    t = text.strip()
    if "Português" in lang_label:
        known_acronyms = {"IBGE", "UFJF", "UFU", "UFMG", "UFV", "UFSJ", "IDH", "PIB", "ONU", "EUA", "SUS", "CPF", "CNPJ"}
        def _decap(m):
            w = m.group(0)
            if w in known_acronyms:
                return w
            return w.capitalize()
        t = re.sub(r'\b[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]{4,}\b', _decap, t)

        pt_names = {
            r'\bGoliath\b': 'Golias',
            r'\bDavid\b': 'Davi',
            r'\bSolomon\b': 'Salomão',
            r'\bMoses\b': 'Moisés',
            r'\bNoah\b': 'Noé',
            r'\bAbraham\b': 'Abraão',
            r'\bIsaac\b': 'Isaque',
            r'\bJacob\b': 'Jacó',
            r'\bJoseph\b': 'José',
            r'\bJoshua\b': 'Josué',
            r'\bElijah\b': 'Elias',
            r'\bElisha\b': 'Eliseu',
            r'\bJonah\b': 'Jonas',
            r'\bSamson\b': 'Sansão',
            r'\bSaul\b': 'Saul',
            r'\bElah\b': 'Elá',
            r'\bBethlehem\b': 'Belém',
            r'\bJerusalem\b': 'Jerusalém',
            r'\bPhilistines\b': 'filisteus',
            r'\bPhilistine\b': 'filisteu',
            r'\bIsraelites\b': 'israelitas'
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
            f"MANDATORY CONTINUOUS OFF-SCREEN VOICEOVER by the EXACT SAME adult male studio narrator "
            f"(deep chest-resonant baritone 115 Hz, warm studio mic{extra}; ZERO on-camera host/presenter, ZERO silence, ZERO extra improvised words, "
            f"NEVER use female or child voices)"
        )
    return (
        f"MANDATORY CONTINUOUS OFF-SCREEN VOICEOVER by the EXACT SAME adult female studio narrator "
        f"(smooth mezzo-soprano 195 Hz, warm studio mic{extra}; ZERO on-camera host/presenter, ZERO silence, ZERO extra improvised words, "
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
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": user_prompt}
                        ],
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
                    x_off = (720 - im.width) // 2
                    y_off = (idx * 640) + (640 - im.height) // 2
                    canvas.paste(im, (x_off, y_off))
        else:
            canvas = Image.new("RGB", (1280, 720), (240, 238, 232))
            for idx, f_obj in enumerate([img_a_file, img_b_file]):
                if f_obj is not None:
                    im = Image.open(io.BytesIO(f_obj.getvalue())).convert("RGB")
                    im.thumbnail((610, 680))
                    x_off = (idx * 640) + (640 - im.width) // 2
                    y_off = (720 - im.height) // 2
                    canvas.paste(im, (x_off, y_off))
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
                            spoken_piece = " ".join(buckets[i]).strip()
                            if not spoken_piece:
                                spoken_piece = f"Continuação instrumental e paisagem cinematográfica da cena {i + 1}"
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
        f"Is this a narrative story featuring 1 or 2 specific named recurring human/animated protagonists (e.g., David & Goliath, a specific family story)?\n"
        f"- If NO (city comparison, geography, curiosity list, economy, nature, history overview, or general documentary): output ONLY the word NONE.\n"
        f"- If YES: write ONE concise English Lock Sheet (max 45 words total) defining the fictionalized appearance: EXACT unchanging hairstyle, hair color, skin tone, age, biological sex, and period-accurate outfit color for the 1 or 2 main recurring characters (NEVER use modern clothes in ancient stories, NEVER invent a TV host/narrator character!).\n"
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
            f"Story / Situation: '{title}'\n"
            f"Video Framing: {aspect_framing}\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n"
            f"Character A: {ca_info}\n"
            f"Character B: {cb_info}\n\n"
            f"RULES:\n"
            f"1. STRICT CHRONOLOGICAL PROGRESSION (ZERO REPETITION): Every scene MUST advance the story forward from setup to resolution.\n"
            f"2. ERA-APPROPRIATE SETTING: Set every [CENA: ...] in the authentic location of '{title}' (NEVER an indoor modern room unless modern).\n"
            f"3. NATIVE SPEECH & ONE SPEAKER PER SCENE: Alternate PERSONAGEM A and PERSONAGEM B speaking authentic {lang_en} (12 to 17 words per scene).\n"
            f"4. NO BLANK LINES INSIDE A SCENE BLOCK.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Continuous shot in the authentic setting of the story in English, active speaker talking, zero text]\n"
            f"PERSONAGEM A: Authentic line in {lang_en} (12-17 words, zero abbreviations)."
        )
    else:
        if single_char_desc.strip():
            char_hint = f"the exact protagonist ({single_char_desc.strip()}) with identical hair and outfit in every scene, mouth closed"
        elif "Palito" in style_choice:
            char_hint = "white stick figure characters dressed appropriately for the story's era and context"
        elif "Cartoon" in style_choice:
            char_hint = (
                "3D stylized animated characters with IDENTICAL hairstyle/color in every scene and STRICTLY PERIOD-ACCURATE clothing "
                "(e.g., ancient woven tunics/sandals for biblical stories, NEVER modern caps, suits, or t-shirts)"
            )
        else:
            char_hint = (
                "pure cinematic documentary B-roll footage of real architecture, streets, green mountains, parks, campuses, or historical locations "
                "(STRICTLY ZERO TV presenters/hosts, ZERO people doing thumbs up, ZERO scoreboards/maps/text, ZERO snow in Brazil, ZERO ocean in inland states like Minas Gerais)"
            )

        prompt_text = (
            f"You are a master storyteller and fact-checked documentary screenwriter.\n"
            f"Topic / Story Title: '{title}'\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n\n"
            f"CRITICAL STORYTELLING & PURE DOCUMENTARY B-ROLL RULES:\n"
            f"1. STRICT LINEAR CHRONOLOGY (1 TO {num_scenes}): Setup -> Development -> Climax -> Resolution -> Call-to-Action.\n"
            f"2. PURE CINEMATIC VISUALS: Feature {char_hint}. Even during score updates or Call-to-Action ('like/subscribe/comment'), [CENA:] MUST show sweeping sunset drone shots or landmarks — NEVER show a presenter, YouTuber, scoreboard, map, or subscribe button!\n"
            f"3. 100% NATIVE NAMES IN {lang_en}: Write proper names translated into {lang_en} (never write normal words in ALL CAPS).\n"
            f"4. DISTINCT VOCABULARY PER SCENE: Make each LOCUÇÃO (14 to 18 words) a complete, natural phrase. All people on screen keep mouths closed.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line, ZERO blank lines between [CENA:] and LOCUÇÃO:):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Single continuous B-roll shot in English, authentic geography/era, mouths closed, zero text/signs]\n"
            f"LOCUÇÃO: Engaging narration in {lang_en} (14-18 words)."
        )

    temp_val = 0.35 if "Diálogo" in audio_mode else 0.22
    sys_msg = "Output ONLY the requested formatted script scenes in strict linear chronological order with pure B-roll visuals and zero on-screen text."
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
        f"(except the Image Prompt which MUST be in English).\n\n"
        f"Script:\n{script_text[:3500]}\n\n"
        f"Style: {style_choice}\n"
        f"Character DNA: {char_dna}\n\n"
        f"Deliver cleanly organized with these exact headings:\n"
        f"1. 🔥 5 TÍTULOS MAGNÉTICOS DE ALTO CTR\n"
        f"2. 📝 DESCRIÇÃO OTIMIZADA COM SEO + CAPÍTULOS (00:00)\n"
        f"3. 🏷️ 20 TAGS DE ALTO VOLUME (comma-separated)\n"
        f"4. 🖼️ PROMPT PRONTO PARA CAPA / THUMBNAIL ({orient}, in English, vivid visual hook, period-accurate wardrobe, zero gibberish text)"
    )
    sys_msg = "You are a YouTube & TikTok viral growth strategist."
    return call_llm_text(sys_msg, seo_prompt, api_key, temperature=0.5)

# ======= AUTO-FATIADOR + DIRETOR VISUAL B-ROLL PURO =======
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

def clean_visual_for_flow(vis_text, is_narration=True):
    if not vis_text:
        return ""
    # Se o [CENA:] do usuário pedia placar piscando, tela dividida com texto, mapa com nomes ou tela final do canal, força o Diretor IA a substituir por B-Roll cinematográfico real!
    bad_ui_triggers = r'(?:placar|tela\s+final|tela\s+dividida|bot[ãa]o\s+de\s+inscri|mapa\s+mostrando|texto\s+na\s+tela|letreiro)'
    if is_narration and re.search(bad_ui_triggers, vis_text, flags=re.IGNORECASE):
        return ""
    v = re.sub(
        r'(?:texto|placar)[^,\]]*?(?:na tela|piscando|animado)\s*:?\s*["“”]?.*?["“”]?(?:$|\+|/)',
        '',
        vis_text,
        flags=re.IGNORECASE
    ).strip(" /+-:,")
    return sanitize_visual_for_veo_safety(v, is_narration_broll=is_narration) if len(v) >= 6 else ""

def looks_non_english_visual(text):
    if not text:
        return True
    if re.search(r'[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]', text):
        return True
    pt_markers = r'\b(vista|aérea|imagem|imagens|tela|dividida|prédios|cidade|ruas|morros|carretas|comércio|feiras|padarias|pôr do sol|câmera|mostrando|pessoas|famílias|centro|bairro|menino|gigante|pedra|vale)\b'
    return bool(re.search(pt_markers, text, flags=re.IGNORECASE))

def extract_scenes_for_prompts(raw_script, lang_label, preserve_1to1_blocks=False, allow_empty_speech=False, is_narration=True):
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
        "Wide cinematic establishing drone shot",
        "Smooth tracking camera shot",
        "Medium cinematic B-roll shot",
        "Sweeping panoramic aerial camera movement",
        "Golden hour push-in shot with natural depth of field"
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
                visual = clean_visual_for_flow(m_cena.group(1).strip(), is_narration=is_narration)
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

    is_narration = ("Diálogo" not in audio_mode)
    clean_key = api_key.strip() if api_key else ""
    if not clean_key:
        for i in pending_indices:
            hint = scenes[i].get("raw_visual_hint", "").strip()
            scenes[i]["visual"] = hint if hint else "Sweeping cinematic 4K aerial B-roll shot of urban avenues and green hills at sunset, zero text"
        return scenes

    if not is_narration:
        subject_rule = f"Two-shot in the authentic setting and era of '{topic_hint or 'the story'}', active speaker talking while listener is silent, period-accurate attire."
    elif char_lock_desc.strip():
        subject_rule = f"Keep recurring character appearance 100% identical across scenes ({char_lock_desc.strip()}), mouths closed, acting naturally."
    elif "Palito" in style_choice:
        subject_rule = "Feature simple white stick figure characters dressed appropriately for the story era."
    elif "Cartoon" in style_choice:
        subject_rule = (
            "Feature 3D stylized animated characters with IDENTICAL hair color/style across all scenes, explicit gender, "
            "and STRICTLY PERIOD-ACCURATE wardrobe matching the story era."
        )
    else:
        subject_rule = (
            "PURE CINEMATIC DOCUMENTARY B-ROLL ONLY: Show real architecture, tree-lined avenues, highways, university campuses, green hills, or parks matching the exact geography and tropical/subtropical climate! "
            "ABSOLUTE BANS: NEVER show a TV presenter, news anchor, YouTuber, or person talking to camera; NEVER show thumbs-up gestures or subscribe buttons; "
            "NEVER show scoreboards, maps, split-screens, or signs with text; NEVER show snow/ice in Brazil; NEVER show ocean/beaches for inland Minas Gerais cities! "
            "If the narration mentions a score ('1 a 0', 'empate'), a question to viewers, or 'like/subscribe/comment', illustrate it ONLY with a majestic sunset drone shot over the city skyline or landmarks!"
        )

    batch_size = 25
    total_batches = math.ceil(len(pending_indices) / batch_size)

    for b_num, start in enumerate(range(0, len(pending_indices), batch_size), 1):
        batch_idxs = pending_indices[start:start + batch_size]
        if progress_placeholder is not None:
            progress_placeholder.info(
                f"🎬 Diretor Visual B-Roll criando cenários puros sem apresentadores/placas (Lote {b_num}/{total_batches})..."
            )

        lines_in = []
        for idx in batch_idxs:
            sc = scenes[idx]
            hint_part = f" | Hint: {sc['raw_visual_hint']}" if sc.get("raw_visual_hint") else ""
            lines_in.append(f"{idx + 1}|Narration: {sc['spoken']}{hint_part}")

        user_p = (
            f"Video Overall Topic: '{topic_hint or 'Documentary / Story'}'\n"
            f"STRICT VISUAL RULES: {subject_rule}\n\n"
            f"For each numbered item below, write ONE specific 8-second continuous camera shot in ENGLISH (16 to 26 words) "
            f"that visually illustrates the real-world subject. NEVER translate YouTube metaphors literally (no presenters, no thumbs-up, no scoreboards, no maps, no snow in Brazil, no text).\n\n"
            f"Format EVERY output line strictly as:\n"
            f"NUMBER|English B-roll visual shot description\n\n"
            f"ITEMS:\n" + "\n".join(lines_in)
        )
        sys_p = "You are a world-class Netflix documentary B-roll cinematographer. Output ONLY 'NUMBER|English visual description' lines."
        out_txt, err = call_llm_text(sys_p, user_p, clean_key, temperature=0.2)

        parsed_map = {}
        if not err and out_txt:
            for ln in out_txt.splitlines():
                m = re.match(r'^\s*(\d+)\s*\|\s*(.+)$', ln.strip())
                if m:
                    s_num = int(m.group(1))
                    vis_en = sanitize_visual_for_veo_safety(
                        re.sub(r'[\r\n"]+', ' ', m.group(2)).strip(" .-"),
                        is_narration_broll=is_narration
                    )
                    if len(vis_en) >= 10:
                        parsed_map[s_num] = vis_en

        for idx in batch_idxs:
            if (idx + 1) in parsed_map:
                scenes[idx]["visual"] = parsed_map[idx + 1]
                scenes[idx]["needs_ai_visual"] = False
            elif not scenes[idx].get("visual"):
                scenes[idx]["visual"] = f"Sweeping cinematic 4K aerial drone shot illustrating {topic_hint or 'the landscape'} in golden hour sunlight, zero text"

    if progress_placeholder is not None:
        progress_placeholder.empty()
    return scenes
# ===================================================================================

# ================= MOTOR LOCAL FFMPEG.WASM v3.3 (TRAVA ANTI-DESLIZAMENTO DE ÁUDIO PRÓPRIO + ANTI-CLONE) =================
FFMPEG_WASM_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8" />
<title>Estúdio Pro — Montador Local FFmpeg.wasm v3.3</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.11.6/dist/ffmpeg.min.js" onerror="var s=document.createElement('script');s.src='https://unpkg.com/@ffmpeg/ffmpeg@0.11.6/dist/ffmpeg.min.js';document.head.appendChild(s);"></script>
<style>
  * { box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }
  body { margin: 0; padding: 12px; background: #0f172a; color: #f8fafc; border-radius: 12px; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 16px; }
  .top-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
  .badge { background: #065f46; color: #6ee7b7; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 720px) { .grid2 { grid-template-columns: 1fr; } }
  .dropzone { border: 2px dashed #3b82f6; background: #0f172a; border-radius: 10px; padding: 15px; text-align: center; cursor: pointer; transition: 0.2s; }
  .dropzone:hover { border-color: #60a5fa; background: #172554; }
  label.lbl { display: block; font-size: 12.5px; font-weight: 600; color: #cbd5e1; margin-bottom: 5px; }
  textarea.script-box { width: 100%; background: #0f172a; color: #f1f5f9; border: 1px solid #475569; border-radius: 8px; padding: 8px; font-size: 12px; resize: vertical; margin-bottom: 10px; }
  select, input[type="range"] { width: 100%; padding: 8px; border-radius: 8px; background: #0f172a; color: #fff; border: 1px solid #475569; font-size: 13px; }
  .chk-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #e2e8f0; margin: 7px 0; cursor: pointer; }
  .btn-main { width: 100%; padding: 13px; border: none; border-radius: 10px; font-size: 15px; font-weight: 700; cursor: pointer; background: linear-gradient(90deg, #2563eb, #1d4ed8); color: #fff; transition: 0.2s; }
  .btn-main:hover:not(:disabled) { background: linear-gradient(90deg, #1d4ed8, #1e40af); }
  .btn-main:disabled { opacity: 0.55; cursor: not-allowed; }
  .btn-sec { background: #334155; color: #f1f5f9; border: 1px solid #475569; border-radius: 8px; padding: 7px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }
  .btn-sec:hover { background: #475569; }
  .prog-wrap { background: #0f172a; border-radius: 999px; height: 12px; overflow: hidden; margin: 10px 0 6px; border: 1px solid #334155; display: none; }
  .prog-bar { background: linear-gradient(90deg, #10b981, #3b82f6); height: 100%; width: 0%; transition: width 0.2s; }
  .status-txt { font-size: 13px; color: #93c5fd; min-height: 20px; margin-bottom: 6px; }
  .dl-box { display: none; background: #064e3b; border: 1px solid #10b981; border-radius: 10px; padding: 14px; margin-top: 12px; }
  .dl-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 10px; margin-top: 10px; }
  .dl-btn { display: block; text-align: center; padding: 12px; border-radius: 8px; font-weight: 700; text-decoration: none; font-size: 14px; }
  .dl-mp4 { background: #10b981; color: #052e16; }
  .dl-srt { background: #0f172a; color: #f8fafc; border: 1px solid #34d399; }
  .log-box { max-height: 210px; overflow-y: auto; background: #020617; border: 1px solid #1e293b; border-radius: 8px; padding: 10px; font-family: monospace; font-size: 11.5px; color: #94a3b8; margin-top: 10px; display: none; }
</style>
</head>
<body>

<div class="card">
  <div class="top-row">
    <div>
      <strong style="font-size:16px;color:#60a5fa;">⚡ Montador Local FFmpeg.wasm v3.3 (Trava Anti-Deslizamento de Sincronia!)</strong>
      <div style="font-size:12px;color:#94a3b8;margin-top:2px;">
        Mantém sincronia cravada até o último segundo mesmo se o Google Flow falhar em algumas cenas do meio!
        Cenas no roteiro: <b id="sc-count-lbl" style="color:#34d399;">0 cenas</b>.
      </div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;">
      <span class="badge">v3.3 Sync-Lock</span>
      <button class="btn-sec" id="open-tab-btn" title="Abre em aba exclusiva com 4GB de RAM dedicados do Chrome">🖥️ Abrir em Aba Dedicada (+RAM)</button>
    </div>
  </div>

  <label class="lbl">📜 Roteiro Completo OU conteúdo de <code>Prompts_Flow.txt</code> (Colar o <code>
