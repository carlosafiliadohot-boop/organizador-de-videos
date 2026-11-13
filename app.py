import os
import io
import re
import math
import hmac
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
    "seo_kit_output": "",
    "auto_duration_min": 1,
    "dna_char_a": DEFAULT_CHAR_A,
    "dna_char_b": DEFAULT_CHAR_B,
    "dna_single_char": "",
    "voice_char_a": "52-year-old Brazilian male baritone voice (105 Hz), calm Minas Gerais accent",
    "voice_char_b": "22-year-old Brazilian young female voice (210 Hz), natural expressive accent"
}.items():
    if k_def not in st.session_state:
        st.session_state[k_def] = v_def

LANGUAGES = {
    "🇧🇷 Português (Brasil)": {
        "sr_code": "pt-BR",
        "name_en": "Brazilian Portuguese (pt-BR)",
        "end_keywords": ["grande abraco", "visitaria primeiro", "proximo video", "proximo dossie", "comente aqui", "ate a proxima", "qual dessas", "inscreva se", "ate o proximo video"]
    },
    "🇪🇸 Espanhol (Latino/Neutro)": {
        "sr_code": "es-MX",
        "name_en": "Latin American Spanish (es-419)",
        "end_keywords": ["gran abrazo", "proximo video", "deja tu comentario", "hasta la proxima", "cual elegirias", "suscribete"]
    },
    "🇺🇸 Inglês (EUA)": {
        "sr_code": "en-US",
        "name_en": "American English (en-US)",
        "end_keywords": ["next video", "leave a comment", "let us know in the comments", "thanks for watching", "see you next time", "subscribe"]
    },
    "🇫🇷 Francês (França)": {
        "sr_code": "fr-FR",
        "name_en": "French (fr-FR)",
        "end_keywords": ["prochaine video", "laissez un commentaire", "a bientot", "merci d avoir regarde", "abonnez vous"]
    },
    "🇮🇹 Italiano (Itália)": {
        "sr_code": "it-IT",
        "name_en": "Italian (it-IT)",
        "end_keywords": ["prossimo video", "lascia un commento", "a presto", "grazie per aver guardato", "iscriviti"]
    }
}

STYLE_PRESETS = {
    "Cinematográfico Realista 4K": (
        "Photorealistic 4K documentary footage, single continuous camera shot, natural daylight, zero text or signs on screen."
    ),
    "Cartoon 3D Pixar": (
        "3D Pixar-style animated film look, vibrant colors, soft lighting, single continuous shot, zero text on screen."
    ),
    "Boneco Palito 2D (Com Boné Azul)": (
        "2D flat vector animation, consistent white stick figure character wearing a blue cap, single continuous shot, zero text."
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
        "2. Abra chrome://extensions no navegador e REMOVA a versão 1.0 antiga.\n"
        "3. Clique em 'Carregar sem compactação' e selecione a nova pasta extraída.\n"
        "4. Recarregue a página do Google Flow (F5) — o painel agora mostrará 'Auto Flow v2.0' em verde!\n"
        "IMPORTANTE NO GOOGLE FLOW: Use o modelo Veo 3 (com áudio ativo) e deixe a varinha de 'Expandir/Reescrever comando' DESATIVADA."
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
        return f"Same 35-year-old male documentary narrator (warm deep baritone 115 Hz, clean studio mic{extra})"
    return f"Same 32-year-old female documentary narrator (warm smooth mezzo-soprano 195 Hz, clean studio mic{extra})"

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
                    if len(out) >= 40:
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
                if len(out) >= 40:
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
        "(30 to 45 words) to lock visual identity across AI video scenes: apparent age, skin tone, hair, facial hair, "
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
            blocks.append(f"[{t1} - {t2}]\n[CENA: Single continuous cinematic shot illustrating: {spoken_piece}, characters silent]\nLOCUÇÃO: {spoken_piece}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return "\n\n".join(blocks), dur, num_chunks

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
            f"1. ZERO REPEATED QUESTIONS: Track details revealed in earlier scenes and advance logically.\n"
            f"2. NATIVE SPEECH: Write authentic everyday {lang_en}, strictly 12 to 17 words per scene.\n"
            f"3. ONE SPEAKER PER SCENE: Alternate PERSONAGEM A and PERSONAGEM B.\n"
            f"4. FIXED SETTING: Keep BOTH characters in the exact same room and lighting across all {num_scenes} scenes.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Medium two-shot in the same room in English, active speaker talking while listener is silent, zero text]\n"
            f"PERSONAGEM A: Authentic line in {lang_en} (12-17 words, zero abbreviations)."
        )
    else:
        if single_char_desc.strip():
            char_hint = f"the protagonist ({single_char_desc.strip()}) exploring the real location silently"
        elif "Palito" in style_choice:
            char_hint = "the white stick figure wearing a blue cap exploring the real location"
        elif "Cartoon" in style_choice:
            char_hint = "the 3D character wearing a blue cap exploring the real location"
        else:
            char_hint = "specific cinematic documentary footage of the real named city, landmark, or subject"

        prompt_text = (
            f"You are a rigorous, fact-checked documentary researcher and scriptwriter.\n"
            f"Topic / Title: '{title}'\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n\n"
            f"RULES:\n"
            f"1. 100% VERIFIED REAL FACTS ONLY.\n"
            f"2. SPELL OUT ACRONYMS AND UNITS in full words in {lang_en}.\n"
            f"3. TIMING: Every LOCUÇÃO MUST have strictly 14 to 18 words in {lang_en}.\n"
            f"4. SPECIFIC VISUALS IN ENGLISH: Every [CENA: ...] MUST explicitly name the real city/place/landmark in Brazil or the world in English ({char_hint}), zero text, mouths closed.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Specific continuous shot in English naming the real location, no text, mouths closed]\n"
            f"LOCUÇÃO: Verified narration in {lang_en} (14-18 words)."
        )

    temp_val = 0.45 if "Diálogo" in audio_mode else 0.2
    sys_msg = "Output ONLY the requested formatted script scenes."
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
        f"4. 🖼️ PROMPT PRONTO PARA CAPA / THUMBNAIL ({orient}, in English, vivid visual hook, zero gibberish text)"
    )
    sys_msg = "You are a YouTube & TikTok viral growth strategist."
    return call_llm_text(sys_msg, seo_prompt, api_key, temperature=0.5)

# ================= AUTO-FATIADOR DE ROTEIROS LONGOS EM CENAS DE 8s =================
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
        return "Aerial drone shot of Brazilian Minas Gerais city skyline, avenues, and green hills in daylight"
    v = re.sub(
        r'(?:texto|placar)[^,\]]*?(?:na tela|piscando|animado)\s*:?\s*["“”]?.*?["“”]?(?:$|\+|/)',
        '',
        vis_text,
        flags=re.IGNORECASE
    ).strip(" /+-:,")
    if len(v) < 10:
        return "Aerial drone view of Brazilian city avenues, skyscrapers, and green hills in Minas Gerais, Brazil"
    return v

def extract_scenes_for_prompts(raw_script, lang_label):
    pre = re.sub(r'(\[(?:CENA|SCENE)\s*:)', r'\n\n\1', raw_script.strip(), flags=re.IGNORECASE)
    pre = re.sub(
        r'((?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala|PERSONAGEM\s*[AB12])\s*(?:\(.*?\))?\s*:)',
        r'\n\1',
        pre,
        flags=re.IGNORECASE
    )

    blocks = re.split(r'\n\s*\n', pre.strip())
    camera_angles = [
        "Aerial drone establishing shot",
        "Smooth street-level gimbal shot",
        "Wide architectural and urban view",
        "High panoramic drone shot",
        "Cinematic tracking shot"
    ]

    scenes = []
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        visual, spoken_parts, speaker_tag = "", [], "NARRATOR"

        for line in lines:
            if re.match(r'^\[?\d{1,2}:\d{2}(?:\s*-\s*\d{1,2}:\d{2})?\]?', line):
                continue
            if re.match(r'^(?:ROUND\s*\d+|ABERTURA|VEREDITO\s+FINAL|ENCERRAMENTO|INTRODU[ÇC][ÃA]O)\b', line, re.IGNORECASE) and ":" not in line:
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

        base_vis = visual if visual else "Aerial drone shot of Brazilian city skyline and avenues in daylight"
        chunks = split_spoken_into_8s_chunks(full_spoken, max_words=18) if full_spoken else [""]

        for c_idx, ch_txt in enumerate(chunks):
            cam_prefix = camera_angles[c_idx % len(camera_angles)]
            varied_vis = f"{cam_prefix} of {base_vis}" if len(chunks) > 1 else base_vis
            scenes.append({"visual": varied_vis, "spoken": ch_txt, "speaker": speaker_tag})

    return scenes
# ===================================================================================

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

        text_line = ""
        if i < len(script_scenes) and script_scenes[i]["spoken"]:
            text_line = script_scenes[i]["spoken"]
        elif item.get("transcript") and item["transcript"] != "(Ordenado por nome)":
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

def parse_script_text(raw, lang_label):
    scenes = extract_scenes_for_prompts(raw, lang_label)
    spoken_lines = [sc["spoken"] for sc in scenes if sc.get("spoken")]
    full_spoken = " ".join(spoken_lines) if spoken_lines else raw
    return normalize_text(full_spoken), normalize_text(raw)

def transcribe_video_audio(video_path, recognizer, temp_wav, sr_lang_code, ffmpeg_exe):
    import speech_recognition as sr
    for start_sec, dur_sec in [('0.0', '8.0'), ('0.6', '7.2'), ('1.2', '6.5'), ('0.0', '4.5')]:
        try:
            cmd = [ffmpeg_exe, '-y', '-ss', start_sec, '-i', video_path, '-t', dur_sec, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', temp_wav]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            with sr.AudioFile(temp_wav) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language=sr_lang_code)
            if text and len(text.strip()) >= 4:
                return text
        except Exception:
            continue
    return ""

def find_position_in_script(transcript, full_spoken_norm, lang_label):
    from rapidfuzz import fuzz
    t_norm = normalize_text(transcript)
    if any(kw in t_norm for kw in LANGUAGES[lang_label]["end_keywords"]):
        return len(full_spoken_norm) + 500, 100
    if t_norm and len(t_norm) >= 4:
        words = t_norm.split()
        script_len = len(full_spoken_norm)
        for n_words in (6, 5, 4, 3, 2):
            if len(words) >= n_words:
                for offset in range(min(3, len(words) - n_words + 1)):
                    snippet = ' '.join(words[offset:offset + n_words])
                    if len(snippet) >= 8:
                        idx = full_spoken_norm.find(snippet)
                        if idx != -1:
                            return max(0, idx - (offset * 6)), 100
        best_pos, best_score = 0, -1
        w_size = max(len(t_norm), 25)
        for pos in range(0, max(1, script_len - 8), 3):
            seg = full_spoken_norm[pos:min(script_len, pos + w_size + 20)]
            score = (fuzz.partial_ratio(t_norm, seg) * 0.65) + (fuzz.token_set_ratio(t_norm, seg) * 0.35)
            if score > best_score:
                best_score, best_pos = score, pos
        if best_score >= 50:
            return best_pos, best_score
    return 999999, 0

# ================= TOPO DO ESTÚDIO & VÍDEO TUTORIAL =================
is_admin = (st.session_state.get("user_role") == "admin")
col_hdr1, col_hdr2 = st.columns([5, 1])
with col_hdr1:
    st.title("🎬 Estúdio Pro Ultimate — Vídeos 16:9 & 9:16, Roteiros, Legendas & SEO")
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

with st.expander("▶️ PASSO A PASSO RÁPIDO: Como criar seu vídeo completo sem cortes de idioma"):
    if tutorial_url:
        st.video(tutorial_url)
    st.markdown(
        "1. **Ative sua Chave Grátis (1x só):** Acesse **[console.groq.com/keys](https://console.groq.com/keys)**, crie a chave `gsk_...` e cole no topo.\n"
        "2. **Crie ou Cole Qualquer Roteiro (Aba 1):** Prompts agora saem em **Linha Única Anti-Corte** para o Google Flow respeitar 100% o cenário e o idioma selecionado.\n"
        "3. **No Google Flow:** Use o modelo **Veo 3 (com Áudio ligado)**, deixe a opção de **Expandir/Reescrever prompt (varinha)** desativada e use a **Extensão VIP v2.0**!\n"
        "4. **Montagem & SEO (Abas 2 e 3):** Suba o `.ZIP` na **Aba 2** para ordenar pela fala em português e baixar o `.MP4` + `.SRT`."
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
    "🎞️ 2. Montagem, Música de Fundo & Legendas (.SRT)",
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
            st.text_area("🧬 DNA Físico Fixo do Protagonista (Opcional — em Inglês):", key="dna_single_char", height=90)

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
    st.markdown("### 🤖 Passo 2: Gerar Roteiro pela IA ou Colar Roteiro Longo")
    col_t1, col_t2, col_t3 = st.columns([3, 1, 1])
    with col_t1:
        video_title = st.text_input("Título, Tema ou Situação do Vídeo:", placeholder="Ex: Juiz de Fora vs Uberlândia / 7 Cidades Baratas de MG")
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
                with st.spinner(f"Criando roteiro de {total_scenes_calc} cenas ({'9:16 Vertical' if is_vertical else '16:9 Horizontal'})..."):
                    script_out, err_msg = generate_ai_script(
                        video_title, total_scenes_calc, selected_lang, style_choice, audio_mode, aspect_short,
                        st.session_state.get("dna_char_a", ""), st.session_state.get("dna_char_b", ""),
                        st.session_state.get("dna_single_char", ""), active_api_key
                    )
                    if err_msg:
                        st.error(err_msg)
                    else:
                        st.session_state["saved_script"] = script_out
                        st.success("✅ Roteiro gerado com sucesso!")

    with cs2:
        script_for_prompts = st.text_area(
            "Roteiro Completo (Editável — se colar parágrafos grandes, o botão abaixo fatia sozinho de 8 em 8s!):",
            value=st.session_state["saved_script"],
            height=260
        )

    if st.button("✨ FATIAR EM CENAS DE 8s & GERAR PROMPTS EM LINHA ÚNICA (SEM CORTE DE IDIOMA)", type="primary", use_container_width=True):
        if not script_for_prompts.strip():
            st.warning("Gere ou cole um roteiro primeiro.")
        else:
            st.session_state["saved_script"] = script_for_prompts
            scenes = extract_scenes_for_prompts(script_for_prompts, selected_lang)
            visual_anchor = custom_style if style_choice == "Personalizado (Definir abaixo)" else STYLE_PRESETS[style_choice]
            lang_en_name = LANGUAGES[selected_lang]["name_en"]
            ref_tag = "Match uploaded reference character image(s). " if has_ref_image else ""

            est_mins = round((len(scenes) * 8) / 60.0, 1)
            st.success(f"✅ {len(scenes)} Cenas em Linha Única prontas (~{est_mins} min) — Idioma travado em {selected_lang}!")
            all_prompts_text = []

            for idx, sc in enumerate(scenes, 1):
                clean_spoken = sc["spoken"].replace('"', "'").strip()
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
                        f"AUDIO RULE (MANDATORY {lang_en_name} ONLY, ZERO ENGLISH, zero music): "
                        f"{active_char} ({active_voice}) speaks clearly in native {lang_en_name}: \"{clean_spoken}\""
                    )
                elif "Modo 3" in audio_mode and mute_flow_for_custom:
                    single_dna = st.session_state.get("dna_single_char", "").strip()
                    char_clause = f"Protagonist: {single_dna}. " if single_dna else ""
                    raw_p = (
                        f"{aspect_short}. {visual_anchor} {ref_tag}{char_clause}"
                        f"Scene action: {sc['visual']}. People keep mouths closed in silence. "
                        f"AUDIO RULE: Silent ambient sound only, zero speech, zero narration, zero music."
                    )
                else:
                    single_dna = st.session_state.get("dna_single_char", "").strip()
                    char_clause = f"Protagonist: {single_dna}. " if single_dna else ""
                    voice_short = get_compact_voice_profile(voice_choice, custom_voice_timbre)
                    raw_p = (
                        f"{aspect_short}. {visual_anchor} {ref_tag}{char_clause}"
                        f"Scene action: {sc['visual']}. Any people on screen keep mouths closed (no lip-sync). "
                        f"AUDIO RULE (MANDATORY {lang_en_name} SPEECH ONLY, ZERO ENGLISH, no background music): "
                        f"Off-screen narrator ({voice_short}) speaks in native {lang_en_name}: \"{clean_spoken}\""
                    )

                # Garante matematicamente ZERO quebras de linha dentro do prompt da cena
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
    st.subheader(f"Montagem por Voz, Trilha Sonora & Legendas Automáticas ({'9:16 Vertical' if is_vertical else '16:9 Horizontal'})")

    col1, col2 = st.columns([1, 1])
    with col1:
        roteiro_input = st.text_area("📜 1. Roteiro Completo do Vídeo (Usado para ordenar e gerar a legenda .SRT):", value=st.session_state["saved_script"], height=290)
        burn_subs = st.checkbox(
            "💬 Gravar legendas embutidas direto na imagem do vídeo (Recomendado para Shorts/TikTok)",
            value=False,
            help="Além de disponibilizar o arquivo .SRT separado para download, desenha as legendas direto no MP4 final."
        )

    with col2:
        uploaded_files = st.file_uploader("📦 2. Envie o .ZIP baixado do Google Flow (ou selecione os .MP4):", type=["zip", "mp4"], accept_multiple_files=True)

        ca_mix1, ca_mix2 = st.columns([1, 1])
        with ca_mix1:
            master_custom_audio = st.file_uploader("🎙️ 3A. Trocar Voz Principal (Opcional):", type=["mp3", "wav", "m4a", "ogg"], key="up_voice_rep")
        with ca_mix2:
            bg_music_file = st.file_uploader("🎵 3B. Música de Fundo Suave (Opcional):", type=["mp3", "wav", "m4a", "ogg"], key="up_bgm")

        bgm_vol_pct = 12
        if bg_music_file is not None:
            bgm_vol_pct = st.slider("🔉 Volume da Música de Fundo (%):", min_value=3, max_value=40, value=12, step=1)

        sort_method = st.radio(
            "Como ordenar os clipes antes de juntar?",
            ["🗣️ Escutar a fala dos clipes e ordenar pelo roteiro (Automático)", "🔢 Ordenar apenas pelo nome dos arquivos (Para vídeos mudos)"]
        )

    if st.button("🚀 ORGANIZAR, MIXAR ÁUDIO E ENTREGAR VÍDEO + LEGENDA (.SRT)", type="primary", use_container_width=True):
        if not uploaded_files:
            st.error("⚠️ Envie o arquivo .ZIP ou os vídeos .MP4 gerados no Google Flow.")
        elif "Escutar" in sort_method and (not roteiro_input or len(roteiro_input.strip()) < 10):
            st.error("Cole o roteiro à esquerda (ou mude para ordenar pelo nome dos arquivos se os vídeos forem mudos).")
        else:
            import speech_recognition as sr
            sem = get_render_semaphore()
            wait_box = st.empty()
            wait_box.info("⏳ Entrando na fila inteligente de renderização...")

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
                        if uf.name.lower().endswith(".zip"):
                            z_path = os.path.join(work_dir, uf.name)
                            with open(z_path, "wb") as f:
                                f.write(uf.getbuffer())
                            with zipfile.ZipFile(z_path, 'r') as z:
                                for m in z.namelist():
                                    if m.lower().endswith('.mp4') and not m.startswith('__MACOSX'):
                                        fn = os.path.basename(m)
                                        if fn:
                                            t_path = os.path.join(extract_dir, fn)
                                            with z.open(m) as src, open(t_path, 'wb') as dst:
                                                shutil.copyfileobj(src, dst)
                                            if os.path.getsize(t_path) > 1000:
                                                mp4_files.append(t_path)
                        elif uf.name.lower().endswith(".mp4"):
                            t_path = os.path.join(extract_dir, uf.name)
                            with open(t_path, "wb") as f:
                                f.write(uf.getbuffer())
                            if os.path.getsize(t_path) > 1000:
                                mp4_files.append(t_path)

                    if not mp4_files:
                        st.error("Nenhum vídeo .MP4 válido foi encontrado.")
                    else:
                        results = []
                        p_bar = st.progress(0, text="Analisando cenas...")
                        total = len(mp4_files)

                        if "Escutar" in sort_method:
                            full_spoken_norm, _ = parse_script_text(roteiro_input, selected_lang)
                            recognizer = sr.Recognizer()
                            temp_wav = os.path.join(work_dir, "_temp.wav")
                            sr_code = LANGUAGES[selected_lang]["sr_code"]
                            for idx, v_path in enumerate(mp4_files, 1):
                                fn = os.path.basename(v_path)
                                tr = transcribe_video_audio(v_path, recognizer, temp_wav, sr_code, ffmpeg_exe)
                                pos, sc = find_position_in_script(tr, full_spoken_norm, selected_lang)
                                dur_c = get_media_duration_sec(v_path, ffmpeg_exe)
                                results.append({'path': v_path, 'original_name': fn, 'transcript': tr, 'position': pos, 'duration': dur_c})
                                p_bar.progress((idx / total) * 0.65, text=f"Escutando cena {idx}/{total}: '{tr[:40]}...'")
                            results.sort(key=lambda x: (x['position'], x['original_name']))
                        else:
                            mp4_files.sort(key=lambda p: os.path.basename(p).lower())
                            for idx, v_path in enumerate(mp4_files, 1):
                                dur_c = get_media_duration_sec(v_path, ffmpeg_exe)
                                results.append({'path': v_path, 'original_name': os.path.basename(v_path), 'transcript': '(Ordenado por nome)', 'position': idx, 'duration': dur_c})
                                p_bar.progress((idx / total) * 0.65, text=f"Preparando cena {idx}/{total}...")

                        srt_content = build_synchronized_srt(results, roteiro_input, selected_lang)
                        srt_file_path = os.path.join(work_dir, "legendas.srt")
                        with open(srt_file_path, "w", encoding="utf-8") as sf:
                            sf.write(srt_content)

                        c_list = os.path.join(ordered_dir, 'lista_uniao.txt')
                        with open(c_list, 'w', encoding='utf-8') as cf:
                            for s_num, item in enumerate(results, 1):
                                n_path = os.path.join(ordered_dir, f"Cena_{s_num:03d}.mp4")
                                shutil.copy2(item['path'], n_path)
                                cf.write(f"file '{n_path.replace(chr(92), '/')}'\n")

                        joined_mp4 = os.path.join(work_dir, "VIDEO_UNIDO_BASE.mp4")
                        p_bar.progress(0.75, text="Unindo todas as cenas...")

                        res = subprocess.run(
                            [ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', c_list, '-c', 'copy', '-movflags', '+faststart', joined_mp4],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE
                        )

                        if res.returncode != 0 or not os.path.exists(joined_mp4) or os.path.getsize(joined_mp4) < 5000:
                            p_bar.progress(0.80, text="Padronizando formato dos clipes...")
                            norm_list = os.path.join(ordered_dir, 'lista_norm.txt')
                            with open(norm_list, 'w', encoding='utf-8') as nf:
                                for s_num, item in enumerate(results, 1):
                                    norm_clip = os.path.join(ordered_dir, f"Norm_{s_num:03d}.mp4")
                                    has_aud = subprocess.run([ffmpeg_exe, '-i', item['path']], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stderr
                                    if "Audio:" in has_aud:
                                        subprocess.run([
                                            ffmpeg_exe, '-y', '-i', item['path'],
                                            '-vf', scale_filter, '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-threads', '2',
                                            '-c:a', 'aac', '-ar', '44100', '-ac', '2', norm_clip
                                        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                    else:
                                        subprocess.run([
                                            ffmpeg_exe, '-y', '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
                                            '-i', item['path'], '-vf', scale_filter,
                                            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-threads', '2',
                                            '-c:a', 'aac', '-shortest', norm_clip
                                        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                    if os.path.exists(norm_clip) and os.path.getsize(norm_clip) > 1000:
                                        nf.write(f"file '{norm_clip.replace(chr(92), '/')}'\n")
                            subprocess.run([ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', norm_list, '-c', 'copy', '-movflags', '+faststart', joined_mp4], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                        out_mp4 = joined_mp4

                        if master_custom_audio is not None and os.path.exists(out_mp4):
                            p_bar.progress(0.86, text="Aplicando sua locução principal...")
                            custom_aud_path = os.path.join(work_dir, "locucao_master" + os.path.splitext(master_custom_audio.name)[1])
                            with open(custom_aud_path, "wb") as fa:
                                fa.write(master_custom_audio.getbuffer())
                            dubbed_mp4 = os.path.join(work_dir, "VIDEO_VOZ_CUSTOM.mp4")
                            res_mux = subprocess.run([
                                ffmpeg_exe, '-y', '-i', out_mp4, '-i', custom_aud_path,
                                '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                                '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', dubbed_mp4
                            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            if res_mux.returncode == 0 and os.path.exists(dubbed_mp4) and os.path.getsize(dubbed_mp4) > 5000:
                                out_mp4 = dubbed_mp4

                        if bg_music_file is not None and os.path.exists(out_mp4):
                            p_bar.progress(0.92, text="Mixando trilha sonora de fundo...")
                            bgm_path = os.path.join(work_dir, "bgm_track" + os.path.splitext(bg_music_file.name)[1])
                            with open(bgm_path, "wb") as fb:
                                fb.write(bg_music_file.getbuffer())
                            bgm_out_mp4 = os.path.join(work_dir, "VIDEO_COM_BGM.mp4")
                            vol_float = round(bgm_vol_pct / 100.0, 3)
                            has_main_aud = "Audio:" in subprocess.run([ffmpeg_exe, '-i', out_mp4], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stderr
                            if has_main_aud:
                                cmd_bgm = [
                                    ffmpeg_exe, '-y', '-i', out_mp4, '-stream_loop', '-1', '-i', bgm_path,
                                    '-filter_complex', f"[1:a]volume={vol_float}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                                    '-map', '0:v:0', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', bgm_out_mp4
                                ]
                            else:
                                cmd_bgm = [
                                    ffmpeg_exe, '-y', '-i', out_mp4, '-stream_loop', '-1', '-i', bgm_path,
                                    '-filter_complex', f"[1:a]volume={vol_float}[aout]",
                                    '-map', '0:v:0', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', bgm_out_mp4
                                ]
                            res_bgm = subprocess.run(cmd_bgm, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            if res_bgm.returncode == 0 and os.path.exists(bgm_out_mp4) and os.path.getsize(bgm_out_mp4) > 5000:
                                out_mp4 = bgm_out_mp4

                        if burn_subs and srt_content.strip() and os.path.exists(out_mp4):
                            p_bar.progress(0.96, text="Gravando legendas dinâmicas no vídeo...")
                            subbed_mp4 = os.path.join(work_dir, "VIDEO_LEGENDADO.mp4")
                            srt_escaped = srt_file_path.replace("\\", "/").replace(":", "\\:")
                            f_size = 15 if is_vertical else 18
                            margin_v = 55 if is_vertical else 28
                            sub_filter = f"subtitles='{srt_escaped}':force_style='Fontsize={f_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV={margin_v}'"
                            res_sub = subprocess.run([
                                ffmpeg_exe, '-y', '-i', out_mp4, '-vf', sub_filter,
                                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-threads', '2',
                                '-c:a', 'copy', '-movflags', '+faststart', subbed_mp4
                            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            if res_sub.returncode == 0 and os.path.exists(subbed_mp4) and os.path.getsize(subbed_mp4) > 5000:
                                out_mp4 = subbed_mp4
                            else:
                                st.warning("⚠️ Vídeo pronto, mas a fonte de legenda embutida não pôde ser aplicada neste servidor — baixe o arquivo .SRT abaixo!")

                        p_bar.progress(1.0, text="Concluído!")
                        if os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 5000:
                            with open(out_mp4, "rb") as f_final:
                                st.session_state["final_video_bytes"] = f_final.read()
                            st.session_state["final_srt_text"] = srt_content
                            st.session_state["final_report"] = [
                                {"original_name": r["original_name"], "transcript": r["transcript"]} for r in results
                            ]
                        else:
                            st.error("❌ O FFmpeg não conseguiu gerar o arquivo final. Verifique os vídeos enviados.")
                finally:
                    shutil.rmtree(work_dir, ignore_errors=True)

    if "final_video_bytes" in st.session_state and st.session_state["final_video_bytes"]:
        v_data = st.session_state["final_video_bytes"]
        size_mb = len(v_data) / (1024 * 1024)
        st.success(f"✅ VÍDEO FINAL PRONTO! ({len(st.session_state.get('final_report', []))} cenas unidas — {size_mb:.1f} MB)")

        dl_c1, dl_c2 = st.columns([2, 1])
        with dl_c1:
            st.download_button(
                "💾 BAIXAR VÍDEO COMPLETO PRONTO (.MP4)",
                data=v_data,
                file_name="VIDEO_FINAL_PRONTO.mp4",
                mime="video/mp4",
                type="primary",
                use_container_width=True
            )
        with dl_c2:
            if st.session_state.get("final_srt_text"):
                st.download_button(
                    "📝 BAIXAR LEGENDA SINCRONIZADA (.SRT)",
                    data=st.session_state["final_srt_text"],
                    file_name="Legenda_Sincronizada.srt",
                    mime="text/plain",
                    use_container_width=True
                )

        st.video(v_data)
        with st.expander("📋 Relatório da Ordem das Cenas"):
            for i, r in enumerate(st.session_state.get("final_report", []), 1):
                st.write(f"**Cena {i:03d}** (`{r['original_name']}`) — 🗣️ *{r['transcript']}*")

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
                    if "Modo 2" in audio_mode else st.session_state.get("dna_single_char", "Cinematic documentary visual")
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
# FIM DO ARQUIVO SAAS v2.0 LINHA UNICA
