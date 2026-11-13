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

def fix_pronunciation(text, lang_label):
    if not text:
        return ""
    t = text.strip()
    if "Português" in lang_label:
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
            f"MANDATORY CONTINUOUS VOICEOVER by the EXACT SAME adult 35-year-old male studio narrator "
            f"(deep chest-resonant baritone 115 Hz, Neumann mic{extra}; ZERO silence, ZERO instrumental-only output, "
            f"NEVER use female or child voices)"
        )
    return (
        f"MANDATORY CONTINUOUS VOICEOVER by the EXACT SAME adult 32-year-old female studio narrator "
        f"(smooth mezzo-soprano 195 Hz, Neumann mic{extra}; ZERO silence, ZERO instrumental-only output, "
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

def transcribe_uploaded_audio_chunks(audio_path, sr_lang_code, ffmpeg_exe):
    import speech_recognition as sr
    dur = get_audio_duration_sec(audio_path, ffmpeg_exe)
    num_chunks = max(1, math.ceil(dur / 8.0))
    recognizer = sr.Recognizer()
    work_dir = tempfile.mkdtemp()
    blocks = []
    try:
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
                spoken_piece = f"Trecho narrado da cena {i+1}"
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
        f"Does this video feature specific recurring human/animated characters (like David & Goliath, historical figures, or a protagonist)?\n"
        f"- If NO (pure city/nature/geography documentary without recurring characters): output ONLY the word NONE.\n"
        f"- If YES: write ONE concise English Lock Sheet (max 45 words total) defining the EXACT unchanging hairstyle, hair color, skin tone, age, biological sex, and period-accurate outfit color for the 1 or 2 main recurring characters so they look 100% identical in every scene (NEVER change hair color or outfit).\n"
        f"Output ONLY 'NONE' or the single-line English character lock description."
    )
    out, err = call_llm_text("Output ONLY 'NONE' or a concise single-line English character visual lock.", p_cast, clean_key, temperature=0.1)
    if err or not out or out.strip().upper().startswith("NONE"):
        return ""
    return re.sub(r'[\r\n"]+', ' ', out).strip()

def generate_ai_script(title, num_scenes, lang_label, style_choice, audio_mode, aspect_framing, char_a_desc="", char_b_desc="", single_char_desc="", api_key=""):
    lang_en = LANGUAGES[lang_label]["name_en"]
    if "Diálogo" in audio_mode:
        prompt_text = (
            f"You are a master screenwriter creating an authentic, high-retention dialogue video.\n"
            f"Story / Situation: '{title}'\n"
            f"Video Framing: {aspect_framing}\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n"
            f"Character A: {char_a_desc}\n"
            f"Character B: {char_b_desc}\n\n"
            f"RULES:\n"
            f"1. STRICT CHRONOLOGICAL PROGRESSION (ZERO REPETITION): Never repeat questions or opening lines. Every scene MUST advance the story forward.\n"
            f"2. NATIVE SPEECH & GENDER ACCURACY: Write authentic {lang_en} (12 to 17 words per scene) with 100% accurate grammatical gender.\n"
            f"3. ONE SPEAKER PER SCENE: Alternate PERSONAGEM A and PERSONAGEM B.\n"
            f"4. FIXED SETTING: Keep BOTH characters in the exact same room and lighting across all {num_scenes} scenes.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Medium two-shot in the same room in English, active speaker talking while listener is silent, zero text]\n"
            f"PERSONAGEM A: Authentic line in {lang_en} (12-17 words, zero abbreviations)."
        )
    else:
        if single_char_desc.strip():
            char_hint = f"the exact protagonist ({single_char_desc.strip()}) with identical hair and outfit in every scene, mouth closed"
        elif "Palito" in style_choice:
            char_hint = "white stick figure characters dressed appropriately for the story's era and context"
        elif "Cartoon" in style_choice:
            char_hint = (
                "3D Pixar-style characters with IDENTICAL hairstyle/color in every scene and STRICTLY PERIOD-ACCURATE clothing "
                "(e.g., ancient woven tunics/sandals for biblical stories, NEVER modern caps or t-shirts)"
            )
        else:
            char_hint = "period-accurate cinematic documentary footage of the real location, historical era, or consistent characters"

        prompt_text = (
            f"You are a master storyteller and fact-checked documentary screenwriter.\n"
            f"Topic / Story Title: '{title}'\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n\n"
            f"CRITICAL STORYTELLING, CHARACTER HAIR/OUTFIT LOCK & NATIVE NAMES RULES:\n"
            f"1. STRICT LINEAR CHRONOLOGY (1 TO {num_scenes}): Scene 1 = initial setup; early scenes = preparation/background (e.g., tending sheep BEFORE going to battlefield); middle scenes = confrontation; late scenes = climax/action; penultimate scene = victory/resolution; Scene {num_scenes} = Call-to-Action. NEVER place battlefield action before peaceful introduction, and NEVER place confrontation after victory!\n"
            f"2. UNCHANGING CHARACTER APPEARANCE: If characters appear, choose ONE exact hair color/style, age, gender, and period-accurate outfit for each character (e.g., '14-year-old boy David with short curly dark-brown hair and beige linen tunic') and repeat those EXACT traits in every [CENA: ...] where they appear (never switch between straight, curly, or red hair!). Visuals feature {char_hint}.\n"
            f"3. 100% NATIVE NAMES IN {lang_en}: In LOCUÇÃO, ALWAYS write proper names translated into {lang_en} (e.g., write 'Davi' and 'Golias' in Portuguese, NEVER 'David' or 'Goliath').\n"
            f"4. DISTINCT VOCABULARY PER SCENE: Make each LOCUÇÃO (13 to 18 words) distinct and progressive so audio alignment is 100% unmistakable. All characters on screen keep mouths closed.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Single continuous shot in English repeating exact character hair/gender/period outfit and action, mouths closed, zero text]\n"
            f"LOCUÇÃO: Engaging narration in {lang_en} using native translated names (13-18 words)."
        )

    temp_val = 0.35 if "Diálogo" in audio_mode else 0.22
    sys_msg = "Output ONLY the requested formatted script scenes in strict linear chronological order with unchanging character hair and wardrobe."
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

# ======= AUTO-FATIADOR + DIRETOR VISUAL AUTOMÁTICO PARA ROTEIROS ENVIADOS =======
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
        if merged and (len(ch.split()) < 7 or len(merged[-1].split()) < 8) and (len(merged[-1].split()) + len(ch.split()) <= 21):
            merged[-1] = f"{merged[-1]} {ch}".strip()
        else:
            merged.append(ch)
    return merged

def clean_visual_for_flow(vis_text):
    if not vis_text:
        return ""
    v = re.sub(
        r'(?:texto|placar)[^,\]]*?(?:na tela|piscando|animado)\s*:?\s*["“”]?.*?["“”]?(?:$|\+|/)',
        '',
        vis_text,
        flags=re.IGNORECASE
    ).strip(" /+-:,")
    return v if len(v) >= 6 else ""

def looks_non_english_visual(text):
    if not text:
        return True
    if re.search(r'[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]', text):
        return True
    pt_markers = r'\b(vista|aérea|imagem|imagens|tela|dividida|prédios|cidade|ruas|morros|carretas|comércio|feiras|padarias|pôr do sol|câmera|mostrando|pessoas|famílias|centro|bairro|menino|gigante|pedra|vale)\b'
    return bool(re.search(pt_markers, text, flags=re.IGNORECASE))

def extract_scenes_for_prompts(raw_script, lang_label):
    if not raw_script or not raw_script.strip():
        return []
    pre = re.sub(r'(\[(?:CENA|SCENE)\s*:)', r'\n\n\1', raw_script.strip(), flags=re.IGNORECASE)
    pre = re.sub(
        r'((?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala|PERSONAGEM\s*[AB12])\s*(?:\(.*?\))?\s*:)',
        r'\n\1',
        pre,
        flags=re.IGNORECASE
    )

    blocks = re.split(r'\n\s*\n', pre.strip())
    camera_angles = [
        "Wide cinematic establishing shot",
        "Smooth tracking camera shot",
        "Medium expressive cinematic shot",
        "Sweeping panoramic camera movement",
        "Dynamic push-in shot with shallow depth of field"
    ]

    scenes = []
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        visual, spoken_parts, speaker_tag = "", [], "NARRATOR"

        for line in lines:
            if re.match(r'^\[?\d{1,2}:\d{2}(?:\s*-\s*\d{1,2}:\d{2})?\]?', line):
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

        full_spoken = " ".join(p for p in spoken_parts if p).strip()
        if not full_spoken and not visual:
            continue

        chunks = split_spoken_into_8s_chunks(full_spoken, max_words=18) if full_spoken else [""]
        has_user_vis = bool(visual.strip())

        for c_idx, ch_txt in enumerate(chunks):
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
    if not clean_key:
        for i in pending_indices:
            hint = scenes[i].get("raw_visual_hint", "").strip()
            scenes[i]["visual"] = hint if hint else "Cinematic 4K footage illustrating the narrated scene with period-accurate wardrobe, zero text"
        return scenes

    if "Diálogo" in audio_mode:
        subject_rule = "Medium two-shot in the exact same room showing the active speaker talking while the other listens silently."
    elif char_lock_desc.strip():
        subject_rule = f"Keep character appearance 100% identical across scenes ({char_lock_desc.strip()}), mouths closed."
    elif "Palito" in style_choice:
        subject_rule = "Feature simple white stick figure characters dressed appropriately for the story era."
    elif "Cartoon" in style_choice:
        subject_rule = (
            "Feature 3D Pixar-style characters with IDENTICAL hair color/style across all scenes, explicit gender, "
            "and STRICTLY PERIOD-ACCURATE wardrobe matching the story era."
        )
    else:
        subject_rule = "Cinematic footage matching the exact historical era, real named location, and consistent character appearance, mouths closed."

    batch_size = 25
    total_batches = math.ceil(len(pending_indices) / batch_size)

    for b_num, start in enumerate(range(0, len(pending_indices), batch_size), 1):
        batch_idxs = pending_indices[start:start + batch_size]
        if progress_placeholder is not None:
            progress_placeholder.info(
                f"🎬 Diretor Visual IA criando cenários consistentes em inglês (Lote {b_num}/{total_batches})..."
            )

        lines_in = []
        for idx in batch_idxs:
            sc = scenes[idx]
            hint_part = f" | Visual Hint: {sc['raw_visual_hint']}" if sc.get("raw_visual_hint") else ""
            lines_in.append(f"{idx + 1}|Narration: {sc['spoken']}{hint_part}")

        user_p = (
            f"Video Overall Topic: '{topic_hint or 'Story / Documentary'}'\n"
            f"Character & Wardrobe Lock: {subject_rule}\n\n"
            f"For each numbered item below, write ONE specific 8-second continuous camera shot in ENGLISH (16 to 26 words) "
            f"that visually illustrates the exact action of that narration line. Keep recurring characters' hair color, hairstyle, and outfit 100% identical. "
            f"STRICTLY NO on-screen text, NO signs, NO modern clothes in ancient stories.\n\n"
            f"Format EVERY output line strictly as:\n"
            f"NUMBER|English visual shot description\n\n"
            f"ITEMS:\n" + "\n".join(lines_in)
        )
        sys_p = "You are an expert AI film director for Google Veo. Output ONLY 'NUMBER|English visual description' lines."
        out_txt, err = call_llm_text(sys_p, user_p, clean_key, temperature=0.22)

        parsed_map = {}
        if not err and out_txt:
            for ln in out_txt.splitlines():
                m = re.match(r'^\s*(\d+)\s*\|\s*(.+)$', ln.strip())
                if m:
                    s_num = int(m.group(1))
                    vis_en = re.sub(r'[\r\n"]+', ' ', m.group(2)).strip(" .-")
                    if len(vis_en) >= 10:
                        parsed_map[s_num] = vis_en

        for idx in batch_idxs:
            if (idx + 1) in parsed_map:
                scenes[idx]["visual"] = parsed_map[idx + 1]
                scenes[idx]["needs_ai_visual"] = False
            elif not scenes[idx].get("visual"):
                scenes[idx]["visual"] = f"Cinematic continuous shot illustrating {topic_hint or 'the narrated scene'}, period-accurate setting, zero text"

    if progress_placeholder is not None:
        progress_placeholder.empty()
    return scenes
# ===================================================================================

# ================= MOTOR LOCAL FFMPEG.WASM v2.7 (SINGLE-THREAD / ZERO WORKER BLOCK) =================
FFMPEG_WASM_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8" />
<title>Estúdio Pro — Montador Local FFmpeg.wasm v2.7</title>
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
  .prog-bar { background: linear-gradient(90deg, #10b981, #3b82f6); height: 100%; width: 0%; transition: width 0.25s; }
  .status-txt { font-size: 13px; color: #93c5fd; min-height: 20px; margin-bottom: 6px; }
  .dl-box { display: none; background: #064e3b; border: 1px solid #10b981; border-radius: 10px; padding: 14px; margin-top: 12px; }
  .dl-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 10px; margin-top: 10px; }
  .dl-btn { display: block; text-align: center; padding: 12px; border-radius: 8px; font-weight: 700; text-decoration: none; font-size: 14px; }
  .dl-mp4 { background: #10b981; color: #052e16; }
  .dl-srt { background: #0f172a; color: #f8fafc; border: 1px solid #34d399; }
  .log-box { max-height: 195px; overflow-y: auto; background: #020617; border: 1px solid #1e293b; border-radius: 8px; padding: 10px; font-family: monospace; font-size: 11.5px; color: #94a3b8; margin-top: 10px; display: none; }
</style>
</head>
<body>

<div class="card">
  <div class="top-row">
    <div>
      <strong style="font-size:16px;color:#60a5fa;">⚡ Montador Local FFmpeg.wasm v2.7 (Single-Thread Anti-Bloqueio)</strong>
      <div style="font-size:12px;color:#94a3b8;margin-top:2px;">
        Lê pacotes de <b>900 MB, 1.5 GB ou mais</b> direto do seu computador — zero upload!
        Roteiro detectado: <b id="sc-count-lbl" style="color:#34d399;">0 cenas</b>.
      </div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;">
      <span class="badge">100% RAM Local</span>
      <button class="btn-sec" id="open-tab-btn" title="Abre este montador numa aba exclusiva com memória RAM dedicada do Chrome">🖥️ Abrir em Aba Dedicada (+RAM)</button>
    </div>
  </div>

  <label class="lbl">📜 Roteiro Completo do Vídeo (Já sincronizado com a Aba 1 — ou cole/edite direto aqui sem perder o arquivo selecionado):</label>
  <textarea id="inp-script" class="script-box" rows="4" placeholder="Cole aqui o roteiro completo para alinhar todas as cenas pela fala e gerar a legenda .SRT..."></textarea>

  <div class="grid2">
    <div>
      <label class="lbl">📦 1. Selecione o .ZIP gigante (0.9GB+) ou vários .MP4:</label>
      <div class="dropzone" onclick="document.getElementById('inp-videos').click()">
        <input type="file" id="inp-videos" multiple accept=".zip,.mp4,video/mp4,application/zip" style="display:none" />
        <div id="vid-file-label" style="font-size:13px;color:#93c5fd;font-weight:600;">
          Clique aqui para escolher o .ZIP ou todos os .MP4<br/>
          <span style="font-size:11px;color:#64748b;font-weight:400;">Leitura instantânea na memória local (0 bytes enviados p/ internet)</span>
        </div>
      </div>

      <div class="grid2" style="margin-top:10px;">
        <div>
          <label class="lbl">🎙️ 2A. Trocar Locução (Opcional):</label>
          <input type="file" id="inp-voice" accept="audio/*" style="font-size:11.5px;width:100%;color:#cbd5e1;" />
        </div>
        <div>
          <label class="lbl">🎵 2B. Música de Fundo (Opcional):</label>
          <input type="file" id="inp-bgm" accept="audio/*" style="font-size:11.5px;width:100%;color:#cbd5e1;" />
        </div>
      </div>
      <div id="bgm-vol-wrap" style="margin-top:8px;display:none;">
        <label class="lbl">🔉 Volume da Música de Fundo: <span id="bgm-vol-val">12</span>%</label>
        <input type="range" id="inp-bgm-vol" min="3" max="40" value="12" oninput="document.getElementById('bgm-vol-val').innerText=this.value" />
      </div>
    </div>

    <div>
      <label class="lbl">🧭 3. Como ordenar e filtrar os clipes no navegador?</label>
      <select id="sel-sort">
        <option value="whisper">🗣️ Pareamento IA por Voz (Groq Whisper em Lotes + Exclusivo 1-para-1)</option>
        <option value="chron_flow">🕒 Ordem de Geração do Flow / Nome + Filtro Anti-Mudos Instantâneo</option>
        <option value="alpha">🔢 Ordem Alfabética Pura dos Nomes (Para vídeos intencionalmente mudos)</option>
      </select>

      <label class="chk-row" style="margin-top:10px;">
        <input type="checkbox" id="chk-drop-muted" checked />
        <span>🧹 Descartar automaticamente clipes mudos ou takes extras repetidos</span>
      </label>

      <label class="chk-row">
        <input type="checkbox" id="chk-fast-copy" checked />
        <span>⚡ União Instantânea <code>-c copy</code> (Cola 90+ cenas em segundos sem recodificar!)</span>
      </label>

      <div style="font-size:11.5px;color:#94a3b8;background:#0f172a;padding:8px 10px;border-radius:8px;border:1px solid #334155;margin-top:8px;">
        💡 <b>Núcleo Single-Thread v2.7:</b> Roda direto dentro do quadro do Streamlit sem bloqueio de Worker e une arquivos de 950 MB+ preservando 100% da qualidade original!
      </div>
    </div>
  </div>

  <div style="margin-top:14px;">
    <button class="btn-main" id="btn-run">🚀 MONTAR VÍDEO COMPLETO AGORA NO NAVEGADOR (ZERO UPLOAD)</button>
  </div>

  <div class="prog-wrap" id="prog-wrap"><div class="prog-bar" id="prog-bar"></div></div>
  <div class="status-txt" id="status-txt"></div>

  <div class="dl-box" id="dl-box">
    <div id="dl-summary" style="font-weight:700;color:#6ee7b7;font-size:14px;"></div>
    <div id="dl-missing" style="font-size:12px;color:#fde68a;margin-top:4px;"></div>
    <div class="dl-grid">
      <a id="dl-mp4-link" class="dl-btn dl-mp4" href="#" download="VIDEO_FINAL_COMPLETO.mp4">💾 BAIXAR VÍDEO COMPLETO (.MP4)</a>
      <a id="dl-srt-link" class="dl-btn dl-srt" href="#" download="Legenda_Sincronizada.srt">📝 BAIXAR LEGENDA (.SRT)</a>
    </div>
    <video id="preview-vid" controls style="width:100%;max-height:300px;margin-top:12px;border-radius:8px;background:#000;display:none;"></video>
  </div>

  <div class="log-box" id="log-box"></div>
</div>

<script>
const CONFIG = __CONFIG_JSON__;
const scriptTextarea = document.getElementById("inp-script");
scriptTextarea.value = CONFIG.rawScript || "";

function fixPronJS(t) {
  if (!t) return "";
  let s = t.trim();
  if (CONFIG.whisperLang === "pt") {
    s = s.replace(/\bIBGE\b/g, "I B G E")
         .replace(/\bUFJF\b/g, "U F J F")
         .replace(/\bUFU\b/g, "U F U")
         .replace(/\bUFMG\b/g, "U F M G")
         .replace(/\bIDH\b/g, "I D H")
         .replace(/\bPIB\b/g, "P I B")
         .replace(/\bBH\b/g, "Belo Horizonte")
         .replace(/\bJF\b/g, "Juiz de Fora")
         .replace(/\bMG\b/g, "Minas Gerais")
         .replace(/\bBR[-\s]*040\b/gi, "B R zero quarenta")
         .replace(/(\d+)\s*%/g, "$1 por cento")
         .replace(/\bGoliath\b/g, "Golias")
         .replace(/\bDavid\b/g, "Davi");
  }
  return s.replace(/\s+/g, " ").trim();
}

function splitSpoken8sJS(spokenText, maxWords = 18) {
  const wordsTotal = spokenText.split(/\s+/).filter(Boolean);
  if (wordsTotal.length <= maxWords + 2) return [spokenText.trim()];
  const sentences = spokenText.trim().split(/(?<=[.!?])\s+/);
  const rawChunks = [];
  for (let sent of sentences) {
    sent = sent.trim();
    if (!sent) continue;
    if (sent.split(/\s+/).length <= maxWords) {
      rawChunks.push(sent);
    } else {
      const clauses = sent.split(/(?<=[;:—,])\s+|\s+(?=—)/);
      let curr = "";
      for (let cl of clauses) {
        cl = cl.trim();
        if (!cl) continue;
        const cand = curr ? `${curr} ${cl}`.trim() : cl;
        if (cand.split(/\s+/).length <= maxWords) {
          curr = cand;
        } else {
          if (curr) rawChunks.push(curr);
          const cw = cl.split(/\s+/);
          if (cw.length <= maxWords + 2) {
            curr = cl;
          } else {
            const step = Math.max(12, Math.min(maxWords, Math.ceil(cw.length / Math.ceil(cw.length / maxWords))));
            for (let i = 0; i < cw.length; i += step) {
              const part = cw.slice(i, i + step).join(" ");
              if (i + step < cw.length) rawChunks.push(part);
              else curr = part;
            }
          }
        }
      }
      if (curr) rawChunks.push(curr);
    }
  }
  const merged = [];
  for (const ch of rawChunks) {
    const cwLen = ch.split(/\s+/).length;
    const prevLen = merged.length ? merged[merged.length - 1].split(/\s+/).length : 99;
    if (merged.length && (cwLen < 7 || prevLen < 8) && (prevLen + cwLen <= 21)) {
      merged[merged.length - 1] = `${merged[merged.length - 1]} ${ch}`.trim();
    } else {
      merged.push(ch);
    }
  }
  return merged;
}

function parseScriptScenesJS(raw) {
  if (!raw || !raw.trim()) return [];
  let pre = raw.trim().replace(/(\[(?:CENA|SCENE)\s*:)/gi, "\n\n$1");
  pre = pre.replace(/((?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala|PERSONAGEM\s*[AB12])\s*(?:\(.*?\))?\s*:)/gi, "\n$1");
  const blocks = pre.trim().split(/\n\s*\n/);
  const outScenes = [];
  for (const block of blocks) {
    const lines = block.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    const spokenParts = [];
    for (const line of lines) {
      if (/^\[?\d{1,2}:\d{2}(?:\s*-\s*\d{1,2}:\d{2})?\]?/.test(line)) continue;
      if (/^(?:ROUND\s*\d+|ABERTURA|VEREDITO\s+FINAL|ENCERRAMENTO|INTRODU[ÇC][ÃA]O|CAP[ÍI]TULO\s*\d+|PARTE\s*\d+)\b/i.test(line) && !line.includes(":")) continue;
      if (/^\[?(?:CENA|SCENE)\s*:\s*(.+?)\]?$/i.test(line)) continue;
      const mSpk = line.match(/^(?:PERSONAGEM\s*(?:A|B|1|2)|LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala)\s*(?:\(.*?\))?\s*:\s*(.+)/i);
      if (mSpk) spokenParts.push(fixPronJS(mSpk[1]));
      else spokenParts.push(fixPronJS(line));
    }
    const fullSpoken = spokenParts.filter(Boolean).join(" ").trim();
    if (!fullSpoken) continue;
    const chunks = splitSpoken8sJS(fullSpoken, 18);
    for (const ch of chunks) {
      if (ch) outScenes.push({ spoken: ch });
    }
  }
  return outScenes;
}

function getActiveScenes() {
  const edited = scriptTextarea.value.trim();
  if (!edited) return [];
  if (edited === (CONFIG.rawScript || "").trim() && CONFIG.scenes && CONFIG.scenes.length) {
    return CONFIG.scenes;
  }
  return parseScriptScenesJS(edited);
}

function refreshSceneBadge() {
  const scs = getActiveScenes();
  document.getElementById("sc-count-lbl").innerText = scs.length + " cenas";
}
refreshSceneBadge();
scriptTextarea.addEventListener("input", refreshSceneBadge);

document.getElementById("inp-bgm").addEventListener("change", (e) => {
  document.getElementById("bgm-vol-wrap").style.display = e.target.files.length ? "block" : "none";
});

document.getElementById("inp-videos").addEventListener("change", (e) => {
  const files = [...e.target.files];
  if (!files.length) return;
  const totalMB = (files.reduce((acc, f) => acc + f.size, 0) / (1024 * 1024)).toFixed(1);
  document.getElementById("vid-file-label").innerHTML =
    `✅ <b>${files.length} arquivo(s) selecionado(s) (${totalMB} MB totais)</b><br/><span style="font-size:11px;color:#34d399;">Pronto para processar localmente sem upload!</span>`;
});

document.getElementById("open-tab-btn").addEventListener("click", () => {
  scriptTextarea.textContent = scriptTextarea.value;
  const htmlFull = document.documentElement.outerHTML;
  const blob = new Blob([htmlFull], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
});

function logMsg(msg) {
  const lb = document.getElementById("log-box");
  lb.style.display = "block";
  const div = document.createElement("div");
  div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  lb.appendChild(div);
  lb.scrollTop = lb.scrollHeight;
}

function setProgress(pct, text) {
  document.getElementById("prog-wrap").style.display = "block";
  document.getElementById("prog-bar").style.width = Math.min(100, Math.max(0, pct)) + "%";
  document.getElementById("status-txt").innerText = text;
}

function normalizeText(str) {
  if (!str) return "";
  return str.toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ").trim();
}

function levenshteinRatio(a, b) {
  if (!a && !b) return 100;
  if (!a || !b) return 0;
  const m = a.length, n = b.length;
  const dp = new Uint16Array(n + 1);
  for (let j = 0; j <= n; j++) dp[j] = j;
  for (let i = 1; i <= m; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= n; j++) {
      const temp = dp[j];
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[j] = Math.min(dp[j] + 1, dp[j - 1] + 1, prev + cost);
      prev = temp;
    }
  }
  return ((m + n - dp[n]) / (m + n)) * 100;
}

function tokenSortRatio(a, b) {
  const sa = a.split(" ").filter(Boolean).sort().join(" ");
  const sb = b.split(" ").filter(Boolean).sort().join(" ");
  return levenshteinRatio(sa, sb);
}

function encodeMonoWav12k(int16Samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + int16Samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + int16Samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, int16Samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < int16Samples.length; i++, offset += 2) {
    view.setInt16(offset, int16Samples[i], true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function formatSrtTime(secFloat) {
  const ms = Math.round((secFloat - Math.floor(secFloat)) * 1000);
  const sInt = Math.floor(secFloat);
  const hrs = Math.floor(sInt / 3600);
  const mins = Math.floor((sInt % 3600) / 60);
  const secs = sInt % 60;
  return `${String(hrs).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
}

function buildSrt(orderedItems, scenes) {
  let curr = 0.0, idx = 1;
  const blocks = [];
  for (let i = 0; i < orderedItems.length; i++) {
    const it = orderedItems[i];
    const dur = it.duration > 0.5 ? it.duration : 8.0;
    let txt = "";
    if (it.matchedSceneIdx !== null && scenes[it.matchedSceneIdx] && scenes[it.matchedSceneIdx].spoken) {
      txt = scenes[it.matchedSceneIdx].spoken;
    } else if (it.transcript && !it.transcript.startsWith("(")) {
      txt = it.transcript;
    } else if (i < scenes.length && scenes[i].spoken) {
      txt = scenes[i].spoken;
    }
    if (txt) {
      const words = txt.split(/\s+/);
      if (words.length > 9) {
        const mid = Math.floor(words.length / 2);
        const p1 = words.slice(0, mid).join(" ");
        const p2 = words.slice(mid).join(" ");
        const half = dur / 2.0;
        blocks.push(`${idx++}\n${formatSrtTime(curr)} --> ${formatSrtTime(curr + half - 0.08)}\n${p1}\n`);
        blocks.push(`${idx++}\n${formatSrtTime(curr + half)} --> ${formatSrtTime(curr + dur - 0.12)}\n${p2}\n`);
      } else {
        blocks.push(`${idx++}\n${formatSrtTime(curr)} --> ${formatSrtTime(curr + dur - 0.12)}\n${txt}\n`);
      }
    }
    curr += dur;
  }
  return blocks.join("\n");
}

function assignClipsExclusivelyJS(clips, scenes, endKeywords, dropUnmatched) {
  const numScenes = scenes.length;
  if (!numScenes) {
    const kept = clips.filter(c => !dropUnmatched || !c.isMuted);
    kept.sort((a, b) => a.dateMs - b.dateMs || a.name.localeCompare(b.name, undefined, { numeric: true }));
    kept.forEach((c) => { c.matchedSceneIdx = null; c.score = 100; });
    return { kept, discardedCount: clips.length - kept.length, missingScenes: [] };
  }

  const sceneNorms = scenes.map(s => normalizeText(s.spoken || ""));
  const wordFreq = {};
  const sceneWordSets = sceneNorms.map(sn => {
    const ws = new Set(sn.split(" ").filter(w => w.length >= 4));
    ws.forEach(w => { wordFreq[w] = (wordFreq[w] || 0) + 1; });
    return ws;
  });

  const pairs = [];
  clips.forEach((clip, cIdx) => {
    if (clip.isMuted) return;
    const tNorm = normalizeText(clip.transcript || "");
    if (!tNorm || tNorm.length < 4) return;
    const tWords = new Set(tNorm.split(" ").filter(w => w.length >= 4));
    const hasEndKw = endKeywords.some(kw => tNorm.includes(kw));

    sceneNorms.forEach((sNorm, sIdx) => {
      if (!sNorm) return;
      const rFull = levenshteinRatio(tNorm, sNorm);
      const rSort = tokenSortRatio(tNorm, sNorm);
      let score = (rFull * 0.55) + (rSort * 0.45);

      let rareBonus = 0;
      tWords.forEach(w => {
        if (sceneWordSets[sIdx].has(w)) {
          if (wordFreq[w] === 1) rareBonus += 8.0;
          else if (wordFreq[w] === 2) rareBonus += 3.5;
        }
      });
      score = Math.min(100, score + Math.min(24, rareBonus));
      if (hasEndKw && sIdx === numScenes - 1) score = Math.min(100, score + 18);
      else if (hasEndKw && sIdx < numScenes - 2) score -= 20;

      pairs.push({ score, cIdx, sIdx });
    });
  });

  pairs.sort((a, b) => b.score - a.score);
  const assigned = new Map();
  const usedScenes = new Set();

  for (const p of pairs) {
    if (p.score < 35.0) break;
    if (!assigned.has(p.cIdx) && !usedScenes.has(p.sIdx)) {
      assigned.set(p.cIdx, p);
      usedScenes.add(p.sIdx);
    }
  }

  const kept = [];
  let discardedCount = 0;
  clips.forEach((clip, cIdx) => {
    if (assigned.has(cIdx)) {
      const m = assigned.get(cIdx);
      clip.position = m.sIdx;
      clip.matchedSceneIdx = m.sIdx;
      clip.score = Math.round(m.score * 10) / 10;
      kept.push(clip);
    } else if (!dropUnmatched && !clip.isMuted) {
      clip.position = 99999 + cIdx;
      clip.matchedSceneIdx = null;
      clip.score = 0;
      kept.push(clip);
    } else {
      discardedCount++;
    }
  });

  kept.sort((a, b) => a.position - b.position || a.name.localeCompare(b.name, undefined, { numeric: true }));
  const missingScenes = [];
  for (let i = 0; i < numScenes; i++) {
    if (!usedScenes.has(i)) missingScenes.push(i + 1);
  }
  return { kept, discardedCount, missingScenes };
}

let CACHED_CORE_BLOB_URL = null;
let CACHED_WASM_BLOB_URL = null;

async function fetchAsBlobUrl(url, mimeType) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} ao baixar ${url}`);
  const buf = await resp.arrayBuffer();
  return URL.createObjectURL(new Blob([buf], { type: mimeType }));
}

async function createFreshFFmpegSingleThread() {
  if (!window.FFmpeg || !window.FFmpeg.createFFmpeg) {
    throw new Error("Biblioteca FFmpeg não carregou da CDN. Recarregue a página.");
  }
  if (!CACHED_CORE_BLOB_URL || !CACHED_WASM_BLOB_URL) {
    const cdns = [
      "https://cdn.jsdelivr.net/npm/@ffmpeg/core-st@0.11.1/dist",
      "https://unpkg.com/@ffmpeg/core-st@0.11.1/dist"
    ];
    let lastErr = "Falha ao baixar núcleo WASM";
    for (const base of cdns) {
      try {
        logMsg(`Carregando motor FFmpeg Single-Thread (${base.includes("jsdelivr") ? "jsDelivr" : "unpkg"})...`);
        CACHED_CORE_BLOB_URL = await fetchAsBlobUrl(`${base}/ffmpeg-core.js`, "text/javascript");
        CACHED_WASM_BLOB_URL = await fetchAsBlobUrl(`${base}/ffmpeg-core.wasm`, "application/wasm");
        break;
      } catch (e) {
        lastErr = (e && (e.message || String(e))) || "Erro de rede";
        logMsg("⚠️ Tentando espelho alternativo: " + lastErr);
      }
    }
    if (!CACHED_CORE_BLOB_URL || !CACHED_WASM_BLOB_URL) throw new Error(lastErr);
  }

  const ffmpeg = window.FFmpeg.createFFmpeg({
    mainName: "main",
    corePath: CACHED_CORE_BLOB_URL,
    wasmPath: CACHED_WASM_BLOB_URL,
    workerPath: CACHED_CORE_BLOB_URL,
    log: false
  });
  ffmpeg.setLogger(({ message }) => {
    if (message && !message.startsWith("frame=") && !message.includes("configuration:")) {
      logMsg(message);
    }
  });
  await ffmpeg.load();
  return ffmpeg;
}

async function transcribeBatchGroq(wavBlob, apiKey, langCode) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  for (let attempt = 0; attempt < 4; attempt++) {
    const fd = new FormData();
    fd.append("file", wavBlob, "batch.wav");
    fd.append("model", "whisper-large-v3-turbo");
    fd.append("language", langCode);
    fd.append("response_format", "verbose_json");
    fd.append("timestamp_granularities[]", "word");
    fd.append("timestamp_granularities[]", "segment");

    const resp = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", {
      method: "POST",
      headers: { "Authorization": `Bearer ${apiKey}` },
      body: fd
    });
    if (resp.status === 200) {
      return await resp.json();
    }
    if (resp.status === 429) {
      logMsg("⏳ Pausa rápida de 6s para respeitar limite gratuito da API Whisper...");
      await sleep(6000);
      continue;
    }
    const errTxt = await resp.text();
    throw new Error(`Whisper HTTP ${resp.status}: ${errTxt.slice(0, 120)}`);
  }
  throw new Error("Limite temporário atingido na API Whisper.");
}

document.getElementById("btn-run").addEventListener("click", async () => {
  const rawFiles = [...document.getElementById("inp-videos").files];
  if (!rawFiles.length) {
    alert("⚠️ Selecione primeiro o arquivo .ZIP ou os vídeos .MP4!");
    return;
  }

  const activeScenes = getActiveScenes();
  const sortMode = document.getElementById("sel-sort").value;
  const dropMuted = document.getElementById("chk-drop-muted").checked;
  const fastCopy = document.getElementById("chk-fast-copy").checked;
  const voiceFile = document.getElementById("inp-voice").files[0] || null;
  const bgmFile = document.getElementById("inp-bgm").files[0] || null;
  const bgmVol = parseInt(document.getElementById("inp-bgm-vol").value || "12", 10) / 100.0;

  const btn = document.getElementById("btn-run");
  btn.disabled = true;
  document.getElementById("dl-box").style.display = "none";
  document.getElementById("log-box").innerHTML = "";

  try {
    setProgress(3, "📂 Lendo pacote de vídeos localmente na memória do seu computador...");
    const clipEntries = [];

    for (const f of rawFiles) {
      if (f.name.toLowerCase().endsWith(".zip")) {
        logMsg(`Abrindo pacote local ${f.name} (${(f.size / 1048576).toFixed(1)} MB)...`);
        const zip = await JSZip.loadAsync(f);
        const names = Object.keys(zip.files);
        for (const path of names) {
          const zObj = zip.files[path];
          if (!zObj.dir && path.toLowerCase().endsWith(".mp4") && !path.startsWith("__MACOSX")) {
            const baseName = path.split("/").pop();
            if (baseName && !baseName.startsWith("._")) {
              clipEntries.push({
                name: baseName,
                dateMs: zObj.date ? zObj.date.getTime() : 0,
                getUint8: async () => await zObj.async("uint8array"),
                sizeHint: zObj._data && zObj._data.uncompressedSize ? zObj._data.uncompressedSize : 0
              });
            }
          }
        }
      } else if (f.name.toLowerCase().endsWith(".mp4")) {
        clipEntries.push({
          name: f.name,
          dateMs: f.lastModified || 0,
          getUint8: async () => new Uint8Array(await f.arrayBuffer()),
          sizeHint: f.size
        });
      }
    }

    if (!clipEntries.length) {
      throw new Error("Nenhum vídeo .MP4 válido encontrado dentro da seleção!");
    }
    logMsg(`✅ ${clipEntries.length} clipes .MP4 localizados localmente!`);

    const needAudioCheck = (dropMuted && sortMode !== "alpha") || (sortMode === "whisper");
    const sampleRateTarget = 12000;
    const slotSeconds = 10;
    const pcm12kPerClip = new Array(clipEntries.length).fill(null);

    if (needAudioCheck) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const actx = new AudioCtx();
      try {
        for (let i = 0; i < clipEntries.length; i++) {
          setProgress(5 + ((i + 1) / clipEntries.length) * 28, `🎧 Analisando áudio local do clipe ${i + 1}/${clipEntries.length} (${clipEntries[i].name})...`);
          const bytes = await clipEntries[i].getUint8();
          clipEntries[i].byteLength = bytes.byteLength;
          try {
            const abuf = await actx.decodeAudioData(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
            clipEntries[i].duration = abuf.duration || 8.0;
            const ch0 = abuf.getChannelData(0);
            let sumSq = 0;
            const stepRms = Math.max(1, Math.floor(ch0.length / 8000));
            let countRms = 0;
            for (let k = 0; k < ch0.length; k += stepRms) {
              sumSq += ch0[k] * ch0[k];
              countRms++;
            }
            const rms = Math.sqrt(sumSq / Math.max(1, countRms));
            clipEntries[i].isMuted = (rms < 0.0045);

            if (!clipEntries[i].isMuted && sortMode === "whisper") {
              const ratio = abuf.sampleRate / sampleRateTarget;
              const maxSamples = Math.min(Math.floor(ch0.length / ratio), Math.floor(sampleRateTarget * 8.5));
              const down = new Int16Array(maxSamples);
              for (let s = 0; s < maxSamples; s++) {
                const v = Math.max(-1, Math.min(1, ch0[Math.floor(s * ratio)]));
                down[s] = v < 0 ? v * 0x8000 : v * 0x7FFF;
              }
              pcm12kPerClip[i] = down;
            }
          } catch (decErr) {
            clipEntries[i].duration = 8.0;
            clipEntries[i].isMuted = true;
          }
        }
      } finally {
        try { await actx.close(); } catch (e) {}
      }
    } else {
      clipEntries.forEach(c => { c.duration = 8.0; c.isMuted = false; });
    }

    let orderedClips = [];
    let discardedCount = 0;
    let missingScenes = [];

    const canUseWhisper = (sortMode === "whisper") && CONFIG.groqKey && CONFIG.groqKey.startsWith("gsk_") && activeScenes.length > 0;

    if (sortMode === "whisper" && !canUseWhisper) {
      logMsg("⚠️ Sem roteiro preenchido acima ou sem chave Groq — alinhando pela ordem do pacote + filtro anti-mudos.");
    }

    if (canUseWhisper) {
      const speakableIndices = [];
      clipEntries.forEach((c, idx) => { if (!c.isMuted && pcm12kPerClip[idx]) speakableIndices.push(idx); });
      logMsg(`🗣️ Transcrevendo ${speakableIndices.length} clipes com voz em lotes rápidos via Whisper Turbo...`);

      const batchSize = 8;
      const totalBatches = Math.ceil(speakableIndices.length / batchSize);

      for (let b = 0; b < totalBatches; b++) {
        const sliceIdxs = speakableIndices.slice(b * batchSize, (b + 1) * batchSize);
        setProgress(34 + ((b + 1) / Math.max(1, totalBatches)) * 26, `🧠 Pareando falas IA com as ${activeScenes.length} cenas do roteiro (Lote ${b + 1}/${totalBatches})...`);

        const totalSlotSamples = sliceIdxs.length * slotSeconds * sampleRateTarget;
        const batchPcm = new Int16Array(totalSlotSamples);
        sliceIdxs.forEach((origIdx, slotPos) => {
          batchPcm.set(pcm12kPerClip[origIdx], slotPos * slotSeconds * sampleRateTarget);
          pcm12kPerClip[origIdx] = null;
        });

        const wavBlob = encodeMonoWav12k(batchPcm, sampleRateTarget);
        const wData = await transcribeBatchGroq(wavBlob, CONFIG.groqKey, CONFIG.whisperLang);
        const buckets = Array.from({ length: sliceIdxs.length }, () => []);

        if (wData.words && wData.words.length > 0) {
          for (const w of wData.words) {
            const mid = ((w.start || 0) + (w.end || w.start || 0)) / 2.0;
            const sPos = Math.min(sliceIdxs.length - 1, Math.max(0, Math.floor(mid / slotSeconds)));
            buckets[sPos].push(w.word);
          }
        } else if (wData.segments && wData.segments.length > 0) {
          for (const seg of wData.segments) {
            const mid = ((seg.start || 0) + (seg.end || seg.start || 0)) / 2.0;
            const sPos = Math.min(sliceIdxs.length - 1, Math.max(0, Math.floor(mid / slotSeconds)));
            buckets[sPos].push(seg.text);
          }
        }

        sliceIdxs.forEach((origIdx, slotPos) => {
          clipEntries[origIdx].transcript = buckets[slotPos].join(" ").replace(/\s+/g, " ").trim();
          if (!clipEntries[origIdx].transcript) clipEntries[origIdx].isMuted = true;
        });
      }

      const matchRes = assignClipsExclusivelyJS(clipEntries, activeScenes, CONFIG.endKeywords, dropMuted);
      orderedClips = matchRes.kept;
      discardedCount = matchRes.discardedCount;
      missingScenes = matchRes.missingScenes;

      if (!orderedClips.length && clipEntries.length) {
        logMsg("⚠️ Nenhum pareamento atingiu nota mínima; mantendo clipes com som na ordem original.");
        orderedClips = clipEntries.filter(c => !c.isMuted);
        if (!orderedClips.length) orderedClips = clipEntries;
      }
    } else if (sortMode === "chron_flow" || (sortMode === "whisper" && !canUseWhisper)) {
      orderedClips = clipEntries.filter(c => !dropMuted || !c.isMuted);
      discardedCount = clipEntries.length - orderedClips.length;
      orderedClips.sort((a, b) => (a.dateMs - b.dateMs) || a.name.localeCompare(b.name, undefined, { numeric: true }));
      orderedClips.forEach((c, idx) => {
        c.matchedSceneIdx = idx < activeScenes.length ? idx : null;
        c.transcript = "(Ordem cronológica do pacote)";
        c.score = 100;
      });
    } else {
      orderedClips = [...clipEntries];
      orderedClips.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
      orderedClips.forEach((c, idx) => {
        c.matchedSceneIdx = idx < activeScenes.length ? idx : null;
        c.transcript = "(Ordem alfabética)";
        c.score = 100;
      });
    }

    const totalSelectedMB = orderedClips.reduce((acc, c) => acc + (c.byteLength || c.sizeHint || 0), 0) / 1048576;
    logMsg(`🎬 Cenas válidas alinhadas: ${orderedClips.length} (${totalSelectedMB.toFixed(1)} MB) | Descartados mudos/extras: ${discardedCount}`);

    setProgress(63, "⚙️ Inicializando motor FFmpeg Single-Thread v2.7...");
    let finalMp4Bytes = null;

    if (fastCopy && totalSelectedMB <= 680 && !voiceFile && !bgmFile) {
      // Caminho Direto Ultra-Rápido (1 única execução -c copy em ~6 segundos!)
      const ffmpeg = await createFreshFFmpegSingleThread();
      const listLines = [];
      for (let i = 0; i < orderedClips.length; i++) {
        setProgress(66 + ((i + 1) / orderedClips.length) * 20, `📥 Carregando cena ${i + 1}/${orderedClips.length} na memória local...`);
        const fn = `c_${String(i).padStart(4, "0")}.mp4`;
        ffmpeg.FS("writeFile", fn, await orderedClips[i].getUint8());
        listLines.push(`file '${fn}'`);
      }
      ffmpeg.FS("writeFile", "list.txt", new TextEncoder().encode(listLines.join("\n")));
      setProgress(88, "⚡ Colando todas as cenas instantaneamente (-c copy)...");
      await ffmpeg.run("-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-movflags", "+faststart", "out.mp4");

      for (let i = 0; i < orderedClips.length; i++) {
        try { ffmpeg.FS("unlink", `c_${String(i).padStart(4, "0")}.mp4`); } catch (e) {}
      }
      const rawOut = ffmpeg.FS("readFile", "out.mp4");
      finalMp4Bytes = rawOut.slice();
      try { ffmpeg.FS("unlink", "out.mp4"); ffmpeg.exit(); } catch (e) {}
    } else {
      // Caminho Blindado em Sub-Lotes (Zera a memória WASM a cada bloco de 22 cenas para arquivos > 680MB ou com mixagem!)
      const chunkSize = 22;
      const numChunks = Math.ceil(orderedClips.length / chunkSize);
      const stageUint8List = [];
      const needLightCompress = (!fastCopy) || (totalSelectedMB > 720);

      for (let ch = 0; ch < numChunks; ch++) {
        const ffmpegChunk = await createFreshFFmpegSingleThread();
        const slice = orderedClips.slice(ch * chunkSize, (ch + 1) * chunkSize);
        const listLines = [];
        setProgress(65 + ((ch + 1) / numChunks) * 22, `⚡ Processando bloco seguro ${ch + 1}/${numChunks} (${slice.length} cenas)...`);

        for (let k = 0; k < slice.length; k++) {
          const fn = `in_${k}.mp4`;
          ffmpegChunk.FS("writeFile", fn, await slice[k].getUint8());
          listLines.push(`file '${fn}'`);
        }
        ffmpegChunk.FS("writeFile", "sub.txt", new TextEncoder().encode(listLines.join("\n")));

        if (!needLightCompress) {
          await ffmpegChunk.run("-f", "concat", "-safe", "0", "-i", "sub.txt", "-c", "copy", "stage.mp4");
        } else {
          await ffmpegChunk.run("-f", "concat", "-safe", "0", "-i", "sub.txt", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25", "-c:a", "aac", "-b:a", "128k", "stage.mp4");
        }

        const stData = ffmpegChunk.FS("readFile", "stage.mp4");
        stageUint8List.push(stData.slice());
        try { ffmpegChunk.exit(); } catch (e) {}
      }

      setProgress(89, "🔗 Finalizando união contínua e áudio...");
      const ffmpegFinal = await createFreshFFmpegSingleThread();
      let currentMainFile = "joined_base.mp4";

      if (stageUint8List.length === 1) {
        ffmpegFinal.FS("writeFile", currentMainFile, stageUint8List[0]);
        stageUint8List[0] = null;
      } else {
        const mLines = [];
        for (let s = 0; s < stageUint8List.length; s++) {
          const sName = `st_${s}.mp4`;
          ffmpegFinal.FS("writeFile", sName, stageUint8List[s]);
          stageUint8List[s] = null;
          mLines.push(`file '${sName}'`);
        }
        ffmpegFinal.FS("writeFile", "master.txt", new TextEncoder().encode(mLines.join("\n")));
        await ffmpegFinal.run("-f", "concat", "-safe", "0", "-i", "master.txt", "-c", "copy", "-movflags", "+faststart", currentMainFile);
        for (let s = 0; s < mLines.length; s++) {
          try { ffmpegFinal.FS("unlink", `st_${s}.mp4`); } catch (e) {}
        }
      }

      if (voiceFile) {
        setProgress(93, "🎙️ Aplicando locução principal...");
        const vExt = voiceFile.name.split(".").pop() || "mp3";
        const vInput = `voice_in.${vExt}`;
        ffmpegFinal.FS("writeFile", vInput, new Uint8Array(await voiceFile.arrayBuffer()));
        await ffmpegFinal.run("-i", currentMainFile, "-i", vInput, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", "voiced.mp4");
        try { ffmpegFinal.FS("unlink", currentMainFile); ffmpegFinal.FS("unlink", vInput); } catch (e) {}
        currentMainFile = "voiced.mp4";
      }

      if (bgmFile) {
        setProgress(96, "🎵 Mixando música de fundo...");
        const bExt = bgmFile.name.split(".").pop() || "mp3";
        const bInput = `bgm_in.${bExt}`;
        ffmpegFinal.FS("writeFile", bInput, new Uint8Array(await bgmFile.arrayBuffer()));
        await ffmpegFinal.run(
          "-i", currentMainFile, "-stream_loop", "-1", "-i", bInput,
          "-filter_complex", `[1:a]volume=${bgmVol.toFixed(3)}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]`,
          "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "with_bgm.mp4"
        );
        try { ffmpegFinal.FS("unlink", currentMainFile); ffmpegFinal.FS("unlink", bInput); } catch (e) {}
        currentMainFile = "with_bgm.mp4";
      }

      const fRead = ffmpegFinal.FS("readFile", currentMainFile);
      finalMp4Bytes = fRead.slice();
      try { ffmpegFinal.FS("unlink", currentMainFile); ffmpegFinal.exit(); } catch (e) {}
    }

    setProgress(99, "💾 Gerando link local instantâneo...");
    const mp4Blob = new Blob([finalMp4Bytes], { type: "video/mp4" });
    finalMp4Bytes = null;

    const mp4Url = URL.createObjectURL(mp4Blob);
    const srtText = buildSrt(orderedClips, activeScenes);
    const srtBlob = new Blob([srtText], { type: "text/plain;charset=utf-8" });
    const srtUrl = URL.createObjectURL(srtBlob);

    const finalMB = (mp4Blob.size / 1048576).toFixed(1);
    setProgress(100, "🎉 Vídeo completo unido 100% no seu navegador!");

    const dlBox = document.getElementById("dl-box");
    dlBox.style.display = "block";
    document.getElementById("dl-summary").innerText =
      `✅ VÍDEO PRONTO! ${orderedClips.length} cenas unidas (${finalMB} MB)` +
      (discardedCount > 0 ? ` | 🧹 ${discardedCount} clipe(s) mudo(s)/repetido(s) removido(s)!` : "");

    document.getElementById("dl-missing").innerText = missingScenes.length
      ? `💡 Cenas do roteiro que vieram mudas do Flow e foram omitidas: Cena(s) ${missingScenes.join(", ")}.`
      : "";

    const mp4Link = document.getElementById("dl-mp4-link");
    mp4Link.href = mp4Url;
    mp4Link.innerText = `💾 BAIXAR VÍDEO COMPLETO (${finalMB} MB .MP4)`;

    document.getElementById("dl-srt-link").href = srtUrl;

    const vidPreview = document.getElementById("preview-vid");
    if (mp4Blob.size <= 350 * 1048576) {
      vidPreview.src = mp4Url;
      vidPreview.style.display = "block";
    }

    orderedClips.forEach((c, idx) => {
      logMsg(`Posição ${String(idx + 1).padStart(3, "0")} -> Cena ${c.matchedSceneIdx !== null ? c.matchedSceneIdx + 1 : "Extra"} (${c.score}%) | ${c.name} | "${(c.transcript || "").slice(0, 55)}"`);
    });

  } catch (err) {
    console.error(err);
    const msg = (err && (err.message || String(err))) || "Falha de memória na aba — clique em 'Abrir em Aba Dedicada (+RAM)' no canto superior direito!";
    setProgress(0, "❌ Erro: " + msg);
    logMsg("ERRO DETALHADO: " + msg);
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>
"""

def render_ffmpeg_wasm_assembler(raw_script, lang_label, groq_api_key, is_vertical):
    scenes_parsed = extract_scenes_for_prompts(raw_script, lang_label)
    js_scenes = [{"spoken": sc.get("spoken", "")} for sc in scenes_parsed if sc.get("spoken")]
    cfg = {
        "rawScript": raw_script or "",
        "scenes": js_scenes,
        "groqKey": groq_api_key if (groq_api_key and groq_api_key.startswith("gsk_")) else "",
        "whisperLang": LANGUAGES[lang_label]["whisper_code"],
        "endKeywords": LANGUAGES[lang_label]["end_keywords"],
        "isVertical": is_vertical
    }
    safe_json = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    html_out = FFMPEG_WASM_HTML_TEMPLATE.replace("__CONFIG_JSON__", safe_json)
    components.html(html_out, height=820, scrolling=True)
# ===============================================================================================

def format_srt_timestamp(seconds_float):
    ms = int(round((seconds_float - int(seconds_float)) * 1000))
    s_int = int(seconds_float)
    hrs = s_int // 3600
    mins = (s_int % 3600) // 60
    secs = s_int % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

def build_synchronized_srt(ordered_results, raw_script, lang_label):
    script_scenes = extract_scenes_for_prompts(raw_script, lang_label)
    srt_blocks = []
    curr_time = 0.0
    sub_idx = 1

    for i, item in enumerate(ordered_results):
        clip_dur = item.get("duration", 8.0)
        if clip_dur <= 0.5:
            clip_dur = 8.0

        matched_sc_idx = item.get("matched_scene_idx")
        text_line = ""
        if matched_sc_idx is not None and 0 <= matched_sc_idx < len(script_scenes) and script_scenes[matched_sc_idx]["spoken"]:
            text_line = script_scenes[matched_sc_idx]["spoken"]
        elif item.get("transcript") and item["transcript"] not in ("(Ordenado por nome)", ""):
            text_line = item["transcript"]

        if text_line:
            words = text_line.split()
            if len(words) > 9:
                mid = len(words) // 2
                part1 = " ".join(words[:mid])
                part2 = " ".join(words[mid:])
                half_dur = clip_dur / 2.0
                srt_blocks.append(f"{sub_idx}\n{format_srt_timestamp(curr_time)} --> {format_srt_timestamp(curr_time + half_dur - 0.08)}\n{part1}\n")
                sub_idx += 1
                srt_blocks.append(f"{sub_idx}\n{format_srt_timestamp(curr_time + half_dur)} --> {format_srt_timestamp(curr_time + clip_dur - 0.12)}\n{part2}\n")
                sub_idx += 1
            else:
                srt_blocks.append(f"{sub_idx}\n{format_srt_timestamp(curr_time)} --> {format_srt_timestamp(curr_time + clip_dur - 0.12)}\n{text_line}\n")
                sub_idx += 1

        curr_time += clip_dur

    return "\n".join(srt_blocks)

def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text.lower())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def transcribe_video_audio(video_path, recognizer, temp_wav, sr_lang_code, ffmpeg_exe):
    import speech_recognition as sr
    attempts = [
        ('0.0', '8.2', 'volume=1.6'),
        ('0.2', '7.8', 'volume=1.0'),
        ('0.8', '7.0', 'volume=1.8'),
        ('0.0', '5.0', 'volume=1.5')
    ]
    for start_sec, dur_sec, af_flt in attempts:
        try:
            cmd = [
                ffmpeg_exe, '-y', '-ss', start_sec, '-i', video_path, '-t', dur_sec,
                '-vn', '-af', af_flt, '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', temp_wav
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            with sr.AudioFile(temp_wav) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language=sr_lang_code)
            if text and len(text.strip()) >= 4:
                return text.strip()
        except Exception:
            continue
    return ""

def assign_clips_to_scenes_exclusively(clips_info, raw_script, lang_label, drop_unmatched=True):
    from rapidfuzz import fuzz
    from collections import Counter

    script_scenes = extract_scenes_for_prompts(raw_script, lang_label)
    scene_norms = [normalize_text(sc.get("spoken", "")) for sc in script_scenes]
    num_scenes = len(scene_norms)

    if num_scenes == 0:
        clips_info.sort(key=lambda x: x["original_name"].lower())
        for idx, c in enumerate(clips_info):
            c["position"] = idx
            c["matched_scene_idx"] = None
            c["match_score"] = 100.0
        return clips_info, [], []

    word_freq = Counter()
    scene_word_sets = []
    for sn in scene_norms:
        w_set = {w for w in sn.split() if len(w) >= 4}
        scene_word_sets.append(w_set)
        for w in w_set:
            word_freq[w] += 1

    end_kws = LANGUAGES[lang_label]["end_keywords"]
    candidate_pairs = []

    for c_idx, clip in enumerate(clips_info):
        t_norm = normalize_text(clip.get("transcript", ""))
        if not t_norm or len(t_norm) < 4:
            continue

        t_words = {w for w in t_norm.split() if len(w) >= 4}
        has_end_kw = any(kw in t_norm for kw in end_kws)

        for s_idx, s_norm in enumerate(scene_norms):
            if not s_norm:
                continue

            r_full = fuzz.ratio(t_norm, s_norm)
            r_sort = fuzz.token_sort_ratio(t_norm, s_norm)
            r_set = fuzz.token_set_ratio(t_norm, s_norm)
            base_score = (r_full * 0.45) + (r_sort * 0.35) + (r_set * 0.20)

            s_words = scene_word_sets[s_idx]
            shared_rare_bonus = 0.0
            for sw in (t_words & s_words):
                if word_freq[sw] == 1:
                    shared_rare_bonus += 7.5
                elif word_freq[sw] == 2:
                    shared_rare_bonus += 3.5
            score = min(100.0, base_score + min(22.0, shared_rare_bonus))

            if has_end_kw and s_idx == num_scenes - 1:
                score = min(100.0, score + 18.0)
            elif has_end_kw and s_idx < num_scenes - 2:
                score -= 20.0

            candidate_pairs.append((score, c_idx, s_idx))

    candidate_pairs.sort(key=lambda x: x[0], reverse=True)

    assigned_clips = {}
    used_scenes = set()

    for score, c_idx, s_idx in candidate_pairs:
        if score < 38.0:
            break
        if c_idx not in assigned_clips and s_idx not in used_scenes:
            assigned_clips[c_idx] = (float(s_idx), s_idx, score)
            used_scenes.add(s_idx)

    kept_clips = []
    discarded_clips = []

    for c_idx, clip in enumerate(clips_info):
        if c_idx in assigned_clips:
            pos_val, sc_i, sc_score = assigned_clips[c_idx]
            clip["position"] = pos_val
            clip["matched_scene_idx"] = sc_i
            clip["match_score"] = round(sc_score, 1)
            kept_clips.append(clip)
        else:
            clip["position"] = 99999.0 + c_idx
            clip["matched_scene_idx"] = None
            clip["match_score"] = 0.0
            if drop_unmatched:
                discarded_clips.append(clip)
            else:
                kept_clips.append(clip)

    kept_clips.sort(key=lambda x: (x["position"], x["original_name"].lower()))
    missing_scene_numbers = [idx + 1 for idx in range(num_scenes) if idx not in used_scenes]

    return kept_clips, discarded_clips, missing_scene_numbers

# ================= TOPO DO ESTÚDIO & VÍDEO TUTORIAL =================
is_admin = (st.session_state.get("user_role") == "admin")
col_hdr1, col_hdr2 = st.columns([5, 1])
with col_hdr1:
    st.title("🎬 Estúdio Pro Ultimate — Vídeos 16:9 & 9:16, FFmpeg.wasm Local & SEO")
with col_hdr2:
    st.caption(f"👤 `{st.session_state.get('user_email', '')}`")
    if st.button("🔒 Sair", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

tutorial_url = ""
try:
    tutorial_url = str(st.secrets.get("TUTORIAL_VIDEO_URL", "")).strip()
except Exception:
    tutorial_url = ""

with st.expander("▶️ PASSO A PASSO RÁPIDO: Como montar vídeos gigantes (950MB+ / 12+ min) sem limite de servidor"):
    if tutorial_url:
        st.video(tutorial_url)
    st.markdown(
        "1. **Ative sua Chave Grátis (1x só):** Acesse **[console.groq.com/keys](https://console.groq.com/keys)**, crie a chave `gsk_...` e cole no topo.\n"
        "2. **Crie ou Cole Qualquer Roteiro (Aba 1):** O sistema fatia em cenas de 8s, trava aparência fixa de personagens e gera prompts em linha única.\n"
        "3. **No Google Flow:** Use **Veo 3 (com Áudio ligado)**, escolha **1 vídeo por prompt** e envie pela **Extensão VIP v2.0**.\n"
        "4. **Montagem Local FFmpeg.wasm v2.7 (Aba 2):** Cole o roteiro direto dentro do painel azul da Aba 2, escolha seu `.ZIP` de 950 MB+ e junte tudo em segundos usando a memória do seu PC!"
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
    "⚡ 2. Montagem Local FFmpeg.wasm v2.7 (950MB+ Sem Upload)",
    "🚀 3. Kit Publicação Viral (Títulos, SEO & Capa)"
])

with tab1:
    cf_btn1, cf_btn2 = st.columns([1, 1])
    with cf_btn1:
        components.html(
            """<button onclick="window.open('https://labs.google/fx/pt/tools/flow','FlowPopup','width=980,height=860,left=920,top=60');"
            style="width:100%;padding:10px 14px;background:#1d4ed8;color:white;border:none;border-radius:8px;font-weight:600;font-family:sans-serif;cursor:pointer;font-size:14px;">
            ⚡ Abrir Google Flow em Janela Lateral (Login Seguro)
            </button>""",
            height=48
        )
    with cf_btn2:
        st.download_button(
            "🧩 Baixar Extensão Chrome VIP v2.0 (Linha Única — Áudio PT-BR Garantido)",
            data=build_chrome_extension_zip(),
            file_name="Extensao_VIP_Estudio_Pro_Flow_v2.zip",
            mime="application/zip",
            use_container_width=True
        )

    st.markdown("### 🎛️ Passo 1: Modo de Áudio e Upload dos Personagens")
    audio_mode = st.radio(
        "Como será o áudio e a atuação deste vídeo?",
        [
            "🎙️ Modo 1: Narrador Fixo (Trava Absoluta da Mesma Voz do Início ao Fim)",
            "🗣️ Modo 2: Diálogo Entre Personagens (Upload de Fotos + DNA Físico/Vocal Fixo + Lip-Sync)",
            "🎧 Modo 3: Usar Meu Próprio Áudio Gravado (.MP3 / .WAV — Cenas sincronizadas + troca na montagem)"
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
                ref_audio_file = st.file_uploader("🎵 Opcional: Suba seu áudio (.mp3, .wav, .m4a) para transcrever de 8 em 8s:", type=["mp3", "wav", "m4a", "ogg"])
                mute_flow_for_custom = st.checkbox("Gerar vídeos mudos no Flow", value=False)
                if ref_audio_file is not None:
                    if st.button("🎧 LER MEU ÁUDIO E MONTAR ROTEIRO DE 8 EM 8 SEGUNDOS", use_container_width=True):
                        with st.spinner("Transcrevendo seu áudio em blocos de 8 segundos..."):
                            ffmpeg_exe = get_ffmpeg()
                            tmp_dir_a = tempfile.mkdtemp()
                            try:
                                tmp_aud = os.path.join(tmp_dir_a, ref_audio_file.name)
                                with open(tmp_aud, "wb") as fa:
                                    fa.write(ref_audio_file.getbuffer())
                                t_script, dur_s, n_sc = transcribe_uploaded_audio_chunks(tmp_aud, LANGUAGES[selected_lang]["sr_code"], ffmpeg_exe)
                                st.session_state["saved_script"] = t_script
                                st.success(f"✅ Áudio transcrito ({dur_s:.1f}s -> {n_sc} cenas)!")
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
                            st.session_state["dna_single_char"] = dna_res
                            st.success("✅ DNA visual extraído e travado!")
            st.text_area(
                "🧬 DNA Físico Fixo do Protagonista (Opcional — se deixar vazio em histórias, a IA cria sozinha!):",
                key="dna_single_char",
                height=90
            )

    elif "Modo 2" in audio_mode:
        orient_label = "9:16" if is_vertical else "16:9"
        st.info(f"💡 **Trava Dupla de Identidade ({orient_label}):** Suba a foto do Personagem A e B abaixo! A IA extrai os detalhes e monta o **Cartão Duplo {orient_label}** para subir como *Ingredient* no Google Flow.")
        up_col1, up_col2 = st.columns([1, 1])
        with up_col1:
            up_char_a = st.file_uploader("📸 Subir Foto do Personagem A (Opcional):", type=["png", "jpg", "jpeg", "webp"], key="up_a")
            if up_char_a is not None:
                has_ref_image = True
                st.image(up_char_a, width=140, caption="Foto Personagem A")
        with up_col2:
            up_char_b = st.file_uploader("📸 Subir Foto do Personagem B (Opcional):", type=["png", "jpg", "jpeg", "webp"], key="up_b")
            if up_char_b is not None:
                has_ref_image = True
                st.image(up_char_b, width=140, caption="Foto Personagem B")

        if up_char_a is not None or up_char_b is not None:
            b_col1, b_col2 = st.columns([1, 1])
            with b_col1:
                if st.button("🔍 EXTRAIR DNA FÍSICO E ROUPAS DAS FOTOS ENVIADAS (IA)", type="primary", use_container_width=True):
                    with st.spinner("Lendo traços faciais, cabelo e roupas exatas nas fotos..."):
                        if up_char_a is not None:
                            dna_a, err_a = analyze_character_photo(up_char_a, active_api_key)
                            if err_a:
                                st.error(f"Foto A: {err_a}")
                            else:
                                st.session_state["dna_char_a"] = dna_a
                        if up_char_b is not None:
                            dna_b, err_b = analyze_character_photo(up_char_b, active_api_key)
                            if err_b:
                                st.error(f"Foto B: {err_b}")
                            else:
                                st.session_state["dna_char_b"] = dna_b
                        st.success("✅ DNA físico extraído das fotos com precisão!")
            with b_col2:
                duo_png = build_duo_reference_card(up_char_a, up_char_b, is_vertical=is_vertical)
                if duo_png:
                    st.download_button(
                        f"🖼️ Baixar Cartão {orient_label} dos Personagens (Subir no Flow)",
                        data=duo_png,
                        file_name=f"Referencia_Personagens_Flow_{orient_label.replace(':', 'x')}.png",
                        mime="image/png",
                        use_container_width=True
                    )

        cd1, cd2 = st.columns([1, 1])
        with cd1:
            st.text_area("👤 DNA Físico e Roupa Fixa — Personagem A:", key="dna_char_a", height=105)
            st.text_input("🎙️ Trava de Voz — Personagem A:", key="voice_char_a")
        with cd2:
            st.text_area("👤 DNA Físico e Roupa Fixa — Personagem B:", key="dna_char_b", height=105)
            st.text_input("🎙️ Trava de Voz — Personagem B:", key="voice_char_b")

    st.divider()
    st.markdown("### 🤖 Passo 2: Gerar Roteiro pela IA ou Colar Qualquer Roteiro / Texto Puro")
    col_t1, col_t2, col_t3 = st.columns([3, 1, 1])
    with col_t1:
        video_title = st.text_input("Título ou Tema Geral do Vídeo:", placeholder="Ex: Juiz de Fora vs Uberlândia / A História de Davi e Golias")
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
                with st.spinner(f"Criando roteiro linear cronológico ({total_scenes_calc} cenas)..."):
                    script_out, err_msg = generate_ai_script(
                        video_title, total_scenes_calc, selected_lang, style_choice, audio_mode, aspect_short,
                        st.session_state.get("dna_char_a", ""), st.session_state.get("dna_char_b", ""),
                        st.session_state.get("dna_single_char", ""), active_api_key
                    )
                    if err_msg:
                        st.error(err_msg)
                    else:
                        st.session_state["saved_script"] = script_out
                        st.success("✅ Roteiro linear gerado com sucesso!")

        auto_director_enabled = st.checkbox(
            "🎬 Diretor Visual + Auto-DNA de Elenco (Trava cabelo/roupa automaticamente mesmo sem foto)",
            value=True
        )

    with cs2:
        script_for_prompts = st.text_area(
            "Roteiro ou Texto Puro (Aceita qualquer formato: com/sem tempo, com/sem [CENA:] ou texto corrido puro!):",
            value=st.session_state["saved_script"],
            height=275
        )

    if st.button("✨ FATIAR EM 8s, TRAVAR ELENCO & GERAR PROMPTS EM LINHA ÚNICA", type="primary", use_container_width=True):
        if not script_for_prompts.strip():
            st.warning("Gere ou cole um roteiro/texto primeiro.")
        else:
            st.session_state["saved_script"] = script_for_prompts
            scenes = extract_scenes_for_prompts(script_for_prompts, selected_lang)

            effective_char_lock = st.session_state.get("dna_single_char", "").strip()
            if not effective_char_lock and "Modo 2" not in audio_mode and auto_director_enabled and active_api_key:
                with st.spinner("🧬 Travando aparência fixa dos personagens (cabelo, rosto e traje da época)..."):
                    auto_cast = generate_auto_cast_dna(video_title.strip(), script_for_prompts, style_choice, active_api_key)
                    st.session_state["auto_cast_dna"] = auto_cast
                    effective_char_lock = auto_cast
            elif not effective_char_lock:
                effective_char_lock = st.session_state.get("auto_cast_dna", "")

            if effective_char_lock and "Modo 2" not in audio_mode:
                st.info(f"🧬 **Trava Automática de Aparência Ativada em Todas as Cenas:** `{effective_char_lock}`")

            if auto_director_enabled and any(sc.get("needs_ai_visual") for sc in scenes):
                prog_dir = st.empty()
                scenes = enrich_scenes_with_ai_visuals(
                    scenes,
                    video_title.strip(),
                    style_choice,
                    audio_mode,
                    effective_char_lock,
                    active_api_key,
                    progress_placeholder=prog_dir
                )
            else:
                for sc in scenes:
                    if not sc.get("visual"):
                        sc["visual"] = "Cinematic 4K footage matching the narrated topic with period-accurate wardrobe, zero text on screen"

            visual_anchor = custom_style if style_choice == "Personalizado (Definir abaixo)" else STYLE_PRESETS[style_choice]
            lang_en_name = LANGUAGES[selected_lang]["name_en"]
            ref_tag = "Match uploaded reference character image(s). " if has_ref_image else ""

            est_mins = round((len(scenes) * 8) / 60.0, 1)
            st.success(f"✅ {len(scenes)} Cenas em Linha Única prontas (~{est_mins} min) — Aparência, Época e Idioma travados!")
            all_prompts_text = []

            for idx, sc in enumerate(scenes, 1):
                clean_spoken = fix_pronunciation(sc["spoken"].replace('"', "'").strip(), selected_lang)
                if "Modo 2" in audio_mode:
                    is_a = (sc["speaker"] != "B")
                    active_char = "Character A" if is_a else "Character B"
                    silent_char = "Character B" if is_a else "Character A"
                    active_voice = st.session_state.get("voice_char_a", "") if is_a else st.session_state.get("voice_char_b", "")
                    dna_a_txt = st.session_state.get("dna_char_a", DEFAULT_CHAR_A)
                    dna_b_txt = st.session_state.get("dna_char_b", DEFAULT_CHAR_B)
                    raw_p = (
                        f"{aspect_short}. {visual_anchor} {ref_tag}"
                        f"Character A: {dna_a_txt}. Character B: {dna_b_txt}. "
                        f"Scene action: {sc['visual']}. ONLY {active_char} moves mouth with natural lip-sync while {silent_char} listens silently. "
                        f"AUDIO RULE (MANDATORY AUDIBLE SPEECH IN {lang_en_name}, ZERO SILENT VIDEO, ZERO ENGLISH, zero music): "
                        f"{active_char} ({active_voice}) speaks clearly in native {lang_en_name}: \"{clean_spoken}\""
                    )
                elif "Modo 3" in audio_mode and mute_flow_for_custom:
                    char_clause = f"Character Appearance Lock: {effective_char_lock}. " if effective_char_lock else ""
                    raw_p = (
                        f"{aspect_short}. {visual_anchor} {ref_tag}{char_clause}"
                        f"Scene action: {sc['visual']}. Characters keep mouths closed in silence. "
                        f"AUDIO RULE: Silent ambient sound only, zero speech, zero narration, zero music."
                    )
                else:
                    char_clause = f"Character Appearance Lock (NEVER alter hair or outfit): {effective_char_lock}. " if effective_char_lock else ""
                    voice_short = get_compact_voice_profile(voice_choice, custom_voice_timbre)
                    raw_p = (
                        f"{aspect_short}. {visual_anchor} {ref_tag}{char_clause}"
                        f"Scene action: {sc['visual']}. Characters on screen DO NOT speak and keep mouths closed (off-screen studio narration). "
                        f"VOICE & LANGUAGE LOCK (MANDATORY AUDIBLE VOICEOVER IN {lang_en_name}, NEVER MUTE, ZERO ENGLISH, zero music): "
                        f"{voice_short} speaks clearly in native {lang_en_name}: \"{clean_spoken}\""
                    )

                p_box = re.sub(r'[\r\n]+', ' ', raw_p)
                p_box = re.sub(r'\s+', ' ', p_box).strip()

                all_prompts_text.append(f"=== CENA {idx:03d} ===\n{p_box}\n")
                with st.expander(f"🎬 Cena {idx:03d} ({len(clean_spoken.split())} palavras) — \"{clean_spoken[:65]}...\"", expanded=(idx <= 3)):
                    st.code(p_box, language="text")

            full_txt_joined = "\n".join(all_prompts_text)
            st.download_button("📥 Baixar Todos os Prompts (.TXT)", data=full_txt_joined, file_name="Prompts_Flow.txt", use_container_width=True)
            with st.expander("📋 Ou copie todos os prompts de uma vez para colar na Extensão VIP v2.0"):
                st.code(full_txt_joined, language="text")

with tab2:
    st.subheader(f"Montagem Final ({'9:16 Vertical' if is_vertical else '16:9 Horizontal'})")

    engine_choice = st.radio(
        "⚙️ Escolha onde processar os vídeos:",
        [
            "⚡ Modo Local no Navegador — FFmpeg.wasm v2.7 (Para .ZIP Gigantes de 300MB a 2GB+ — Zero Upload!)",
            "☁️ Modo Nuvem Servidor (Para pacotes menores até ~180MB)"
        ],
        index=0
    )

    if "FFmpeg.wasm" in engine_choice:
        render_ffmpeg_wasm_assembler(st.session_state.get("saved_script", ""), selected_lang, active_api_key, is_vertical)
    else:
        roteiro_input = st.text_area(
            "📜 Roteiro Completo do Vídeo (Usado para alinhar as cenas e gerar a legenda .SRT):",
            value=st.session_state.get("saved_script", ""),
            height=180
        )
        if roteiro_input != st.session_state.get("saved_script", ""):
            st.session_state["saved_script"] = roteiro_input

        static_delivery_dir = os.path.join(os.getcwd(), "static", "entregas")
        os.makedirs(static_delivery_dir, exist_ok=True)
        now_ts = time.time()
        for old_f in os.listdir(static_delivery_dir):
            old_p = os.path.join(static_delivery_dir, old_f)
            try:
                if os.path.isfile(old_p) and (now_ts - os.path.getmtime(old_p)) > 1800:
                    os.remove(old_p)
            except Exception:
                pass

        col1, col2 = st.columns([1, 1])
        with col1:
            drop_muted_dups = st.checkbox("🧹 Ignorar automaticamente clipes mudos ou takes extras duplicados", value=True)
            compress_long_video = st.checkbox("⚡ Otimizar tamanho final para vídeos longos", value=True)
            burn_subs = st.checkbox("💬 Gravar legendas embutidas direto na imagem do vídeo", value=False)
            sort_method = st.radio(
                "Como ordenar os clipes antes de juntar?",
                [
                    "🗣️ Pareamento Exclusivo 1-para-1 pela frase + palavras-chave raras",
                    "🔢 Ordenar apenas pelo nome dos arquivos"
                ]
            )

        with col2:
            up_key = f"zip_uploader_{st.session_state['uploader_reset_id']}"
            uploaded_files = st.file_uploader(
                "📦 Envie o .ZIP (até ~180MB) ou os .MP4:",
                type=["zip", "mp4"],
                accept_multiple_files=True,
                key=up_key
            )
            ca_mix1, ca_mix2 = st.columns([1, 1])
            with ca_mix1:
                master_custom_audio = st.file_uploader("🎙️ Trocar Voz Principal (Opcional):", type=["mp3", "wav", "m4a", "ogg"], key="up_voice_rep")
            with ca_mix2:
                bg_music_file = st.file_uploader("🎵 Música de Fundo (Opcional):", type=["mp3", "wav", "m4a", "ogg"], key="up_bgm")

            bgm_vol_pct = 12
            if bg_music_file is not None:
                bgm_vol_pct = st.slider("🔉 Volume da Música de Fundo (%):", min_value=3, max_value=40, value=12, step=1)

        if st.button("🚀 ORGANIZAR NA NUVEM E GERAR LINK DIRETO", type="primary", use_container_width=True):
            if not uploaded_files:
                st.error("⚠️ Envie o arquivo .ZIP ou os vídeos .MP4.")
            elif "Pareamento" in sort_method and (not roteiro_input or len(roteiro_input.strip()) < 10):
                st.error("Cole o roteiro acima primeiro.")
            else:
                import speech_recognition as sr
                sem = get_render_semaphore()
                wait_box = st.empty()
                wait_box.info("⏳ Entrando na fila de renderização...")

                with sem:
                    wait_box.empty()
                    ffmpeg_exe = get_ffmpeg()
                    work_dir = tempfile.mkdtemp()
                    target_w = 720 if is_vertical else 1280
                    target_h = 1280 if is_vertical else 720
                    scale_filter = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,fps=30"

                    try:
                        extract_dir = os.path.join(work_dir, "extraidos")
                        ordered_dir = os.path.join(work_dir, "ordenados")
                        os.makedirs(extract_dir, exist_ok=True)
                        os.makedirs(ordered_dir, exist_ok=True)

                        mp4_files = []
                        for uf in uploaded_files:
                            uf.seek(0)
                            if uf.name.lower().endswith(".zip"):
                                with zipfile.ZipFile(uf, 'r') as z:
                                    for m in z.namelist():
                                        if m.lower().endswith('.mp4') and not m.startswith('__MACOSX'):
                                            fn = os.path.basename(m)
                                            if fn:
                                                t_path = os.path.join(extract_dir, f"{len(mp4_files):04d}_{fn}")
                                                with z.open(m) as src, open(t_path, 'wb') as dst:
                                                    shutil.copyfileobj(src, dst, length=2 * 1024 * 1024)
                                                if os.path.getsize(t_path) > 1000:
                                                    mp4_files.append(t_path)
                            elif uf.name.lower().endswith(".mp4"):
                                t_path = os.path.join(extract_dir, f"{len(mp4_files):04d}_{uf.name}")
                                with open(t_path, "wb") as f:
                                    shutil.copyfileobj(uf, f, length=2 * 1024 * 1024)
                                if os.path.getsize(t_path) > 1000:
                                    mp4_files.append(t_path)
                            try:
                                uf.close()
                            except Exception:
                                pass

                        del uploaded_files
                        gc.collect()

                        if not mp4_files:
                            st.error("Nenhum vídeo .MP4 válido foi encontrado.")
                        else:
                            raw_clips = []
                            p_bar = st.progress(0, text="Transcrevendo cenas...")
                            total = len(mp4_files)
                            discarded_list = []
                            missing_scenes = []

                            if "Pareamento" in sort_method:
                                recognizer = sr.Recognizer()
                                temp_wav = os.path.join(work_dir, "_temp.wav")
                                sr_code = LANGUAGES[selected_lang]["sr_code"]
                                for idx, v_path in enumerate(mp4_files, 1):
                                    fn = os.path.basename(v_path)
                                    tr = transcribe_video_audio(v_path, recognizer, temp_wav, sr_code, ffmpeg_exe)
                                    dur_c = get_media_duration_sec(v_path, ffmpeg_exe)
                                    raw_clips.append({'path': v_path, 'original_name': fn, 'transcript': tr, 'duration': dur_c})
                                    if idx % 15 == 0:
                                        gc.collect()
                                    p_bar.progress((idx / total) * 0.62, text=f"Escutando clipe {idx}/{total}: '{tr[:40] or '[Sem fala]'}'")
                                results, discarded_list, missing_scenes = assign_clips_to_scenes_exclusively(
                                    raw_clips, roteiro_input, selected_lang, drop_unmatched=drop_muted_dups
                                )
                                for dc in discarded_list:
                                    try:
                                        os.remove(dc["path"])
                                    except Exception:
                                        pass
                                if not results and discarded_list:
                                    results = sorted(discarded_list, key=lambda x: x["original_name"].lower())
                                    discarded_list = []
                            else:
                                mp4_files.sort(key=lambda p: os.path.basename(p).lower())
                                results = []
                                for idx, v_path in enumerate(mp4_files, 1):
                                    dur_c = get_media_duration_sec(v_path, ffmpeg_exe)
                                    results.append({
                                        'path': v_path, 'original_name': os.path.basename(v_path),
                                        'transcript': '(Ordenado por nome)', 'position': idx,
                                        'matched_scene_idx': idx - 1, 'match_score': 100.0, 'duration': dur_c
                                    })
                                    p_bar.progress((idx / total) * 0.65, text=f"Preparando cena {idx}/{total}...")

                            if results:
                                srt_content = build_synchronized_srt(results, roteiro_input, selected_lang)
                                srt_file_path = os.path.join(work_dir, "legendas.srt")
                                with open(srt_file_path, "w", encoding="utf-8") as sf:
                                    sf.write(srt_content)

                                c_list = os.path.join(ordered_dir, 'lista_uniao.txt')
                                with open(c_list, 'w', encoding='utf-8') as cf:
                                    for s_num, item in enumerate(results, 1):
                                        n_path = os.path.join(ordered_dir, f"Cena_{s_num:03d}.mp4")
                                        os.replace(item['path'], n_path)
                                        item['path'] = n_path
                                        cf.write(f"file '{n_path.replace(chr(92), '/')}'\n")

                                joined_mp4 = os.path.join(work_dir, "VIDEO_UNIDO_BASE.mp4")
                                p_bar.progress(0.78, text="Unindo cenas...")
                                subprocess.run(
                                    [ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', c_list, '-c', 'copy', '-movflags', '+faststart', joined_mp4],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                                )
                                shutil.rmtree(extract_dir, ignore_errors=True)
                                shutil.rmtree(ordered_dir, ignore_errors=True)

                                out_mp4 = joined_mp4
                                if compress_long_video and len(results) >= 25 and os.path.exists(out_mp4):
                                    comp_mp4 = os.path.join(work_dir, "COMP.mp4")
                                    subprocess.run([
                                        ffmpeg_exe, '-y', '-i', out_mp4, '-c:v', 'libx264', '-preset', 'ultrafast',
                                        '-crf', '26', '-threads', '1', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', comp_mp4
                                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                    if os.path.exists(comp_mp4) and os.path.getsize(comp_mp4) > 5000:
                                        os.remove(out_mp4)
                                        out_mp4 = comp_mp4

                                if master_custom_audio is not None and os.path.exists(out_mp4):
                                    master_custom_audio.seek(0)
                                    custom_aud_path = os.path.join(work_dir, "loc" + os.path.splitext(master_custom_audio.name)[1])
                                    with open(custom_aud_path, "wb") as fa:
                                        shutil.copyfileobj(master_custom_audio, fa)
                                    dubbed_mp4 = os.path.join(work_dir, "VOZ.mp4")
                                    if subprocess.run([
                                        ffmpeg_exe, '-y', '-i', out_mp4, '-i', custom_aud_path, '-map', '0:v:0', '-map', '1:a:0',
                                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', dubbed_mp4
                                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0 and os.path.exists(dubbed_mp4):
                                        os.remove(out_mp4)
                                        out_mp4 = dubbed_mp4

                                if bg_music_file is not None and os.path.exists(out_mp4):
                                    bg_music_file.seek(0)
                                    bgm_path = os.path.join(work_dir, "bgm" + os.path.splitext(bg_music_file.name)[1])
                                    with open(bgm_path, "wb") as fb:
                                        shutil.copyfileobj(bg_music_file, fb)
                                    bgm_out_mp4 = os.path.join(work_dir, "BGM.mp4")
                                    vol_float = round(bgm_vol_pct / 100.0, 3)
                                    if subprocess.run([
                                        ffmpeg_exe, '-y', '-i', out_mp4, '-stream_loop', '-1', '-i', bgm_path,
                                        '-filter_complex', f"[1:a]volume={vol_float}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                                        '-map', '0:v:0', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', bgm_out_mp4
                                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0 and os.path.exists(bgm_out_mp4):
                                        os.remove(out_mp4)
                                        out_mp4 = bgm_out_mp4

                                if burn_subs and srt_content.strip() and os.path.exists(out_mp4):
                                    subbed_mp4 = os.path.join(work_dir, "SUB.mp4")
                                    srt_escaped = srt_file_path.replace("\\", "/").replace(":", "\\:")
                                    f_size = 15 if is_vertical else 18
                                    margin_v = 55 if is_vertical else 28
                                    sub_filter = f"subtitles='{srt_escaped}':force_style='Fontsize={f_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV={margin_v}'"
                                    if subprocess.run([
                                        ffmpeg_exe, '-y', '-i', out_mp4, '-vf', sub_filter, '-c:v', 'libx264', '-preset', 'ultrafast',
                                        '-crf', '25', '-threads', '1', '-c:a', 'copy', '-movflags', '+faststart', subbed_mp4
                                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0 and os.path.exists(subbed_mp4):
                                        os.remove(out_mp4)
                                        out_mp4 = subbed_mp4

                                p_bar.progress(1.0, text="Concluído!")
                                if os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 5000:
                                    prev_file = st.session_state.get("final_video_disk_path", "")
                                    if prev_file and os.path.exists(prev_file):
                                        try:
                                            os.remove(prev_file)
                                        except Exception:
                                            pass
                                    fname_only = f"VIDEO_FINAL_{uuid.uuid4().hex[:10]}.mp4"
                                    safe_final_path = os.path.join(static_delivery_dir, fname_only)
                                    shutil.move(out_mp4, safe_final_path)
                                    st.session_state["final_video_disk_path"] = safe_final_path
                                    st.session_state["final_video_static_url"] = f"app/static/entregas/{fname_only}"
                                    st.session_state["final_srt_text"] = srt_content
                                    st.session_state["uploader_reset_id"] += 1
                                    gc.collect()
                                    st.rerun()
                    finally:
                        shutil.rmtree(work_dir, ignore_errors=True)
                        gc.collect()

        final_disk_p = st.session_state.get("final_video_disk_path", "")
        if final_disk_p and os.path.exists(final_disk_p):
            size_mb = os.path.getsize(final_disk_p) / (1024 * 1024)
            static_rel_url = st.session_state.get("final_video_static_url", "")
            st.success(f"✅ VÍDEO PRONTO NA NUVEM! ({size_mb:.1f} MB)")
            dl_c1, dl_c2 = st.columns([2, 1])
            with dl_c1:
                st.markdown(
                    f'''<a href="{static_rel_url}" download="VIDEO_FINAL_COMPLETO.mp4" target="_blank"
                    style="display:block;text-align:center;background:#16a34a;color:#ffffff;padding:13px 18px;
                    border-radius:8px;font-weight:700;text-decoration:none;font-size:15px;">
                    ⚡ BAIXAR VÍDEO DIRETO DO DISCO ({size_mb:.1f} MB)
                    </a>''',
                    unsafe_allow_html=True
                )
            with dl_c2:
                if st.session_state.get("final_srt_text"):
                    st.download_button(
                        "📝 BAIXAR LEGENDA (.SRT)",
                        data=st.session_state["final_srt_text"],
                        file_name="Legenda_Sincronizada.srt",
                        mime="text/plain",
                        use_container_width=True
                    )

with tab3:
    st.subheader("🚀 Kit Completo de Publicação Viral (Títulos, Descrição SEO, Tags & Capa)")
    st.caption("Gera automaticamente os metadados prontos para copiar e colar no YouTube, TikTok, Reels ou Shorts.")

    seo_topic = st.text_input("Tema ou Título Base do Projeto:", value=video_title if 'video_title' in locals() else "", placeholder="Ex: Juiz de Fora vs Uberlândia: Qual a Verdadeira Capital do Interior?")
    seo_script_ref = st.text_area("Roteiro de Referência:", value=st.session_state.get("saved_script", ""), height=180)

    if st.button("✨ GERAR TÍTULOS VIRAIS, DESCRIÇÃO COM CAPÍTULOS, TAGS E PROMPT DE CAPA", type="primary", use_container_width=True):
        if not seo_topic.strip() and not seo_script_ref.strip():
            st.warning("Gere um roteiro na Aba 1 ou digite o tema acima primeiro.")
        else:
            with st.spinner("Criando estratégia de alto CTR, SEO e prompt da capa..."):
                combined_dna = (
                    f"Char A: {st.session_state.get('dna_char_a', '')} | Char B: {st.session_state.get('dna_char_b', '')}"
                    if "Modo 2" in audio_mode else (st.session_state.get("dna_single_char", "") or st.session_state.get("auto_cast_dna", "Period-accurate cinematic visual"))
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
# FIM DO ARQUIVO SAAS ULTIMATE v2.7 COMPLETO (SINGLE-THREAD WASM SEM WORKER BLOCK)
