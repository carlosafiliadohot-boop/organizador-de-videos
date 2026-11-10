import os
import io
import re
import math
import base64
import shutil
import zipfile
import tempfile
import subprocess
import unicodedata
import requests
import streamlit as st

st.set_page_config(page_title="Estudio Global Google Flow", page_icon="🎬", layout="wide")

@st.cache_resource
def get_ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

DEFAULT_CHAR_A = (
    "52-year-old Brazilian rural father, tanned weathered skin, square jaw, clean-shaven cheeks with a thick "
    "neatly trimmed dark-gray mustache, wearing a beige woven straw hat with a thin brown leather band and "
    "a solid navy-blue cotton button-up shirt with sleeves rolled to the elbows"
)
DEFAULT_CHAR_B = (
    "22-year-old Brazilian young woman, warm olive skin, oval face, expressive dark brown eyes, shoulder-length "
    "defined dark brown curly hair worn loose, wearing a solid mustard-yellow ribbed t-shirt under a classic "
    "medium-blue denim jacket, small silver stud earrings"
)

if "saved_script" not in st.session_state:
    st.session_state["saved_script"] = ""
if "auto_duration_min" not in st.session_state:
    st.session_state["auto_duration_min"] = 1
if "dna_char_a" not in st.session_state:
    st.session_state["dna_char_a"] = DEFAULT_CHAR_A
if "dna_char_b" not in st.session_state:
    st.session_state["dna_char_b"] = DEFAULT_CHAR_B
if "dna_single_char" not in st.session_state:
    st.session_state["dna_single_char"] = ""
if "voice_char_a" not in st.session_state:
    st.session_state["voice_char_a"] = "Deep, gruff, protective 52-year-old rural male baritone voice (105 Hz), calm interior Minas Gerais cadence"
if "voice_char_b" not in st.session_state:
    st.session_state["voice_char_b"] = "Clear, bright, natural 22-year-old young female voice (210 Hz), expressive Brazilian cadence"

LANGUAGES = {
    "🇧🇷 Português (Brasil)": {
        "sr_code": "pt-BR",
        "name_en": "Brazilian Portuguese (pt-BR)",
        "end_keywords": ["grande abraco", "visitaria primeiro", "proximo video", "proximo dossie", "comente aqui", "ate a proxima", "qual dessas", "inscreva se"]
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
        "Photorealistic 4K cinema footage, ARRI Alexa look, 50mm prime lens, shallow depth of field, "
        "single continuous smooth camera shot, zero scene cuts, zero morphing, natural warm lighting. "
        "Zero text overlays, zero banners, zero signs."
    ),
    "Cartoon 3D Pixar": (
        "3D Pixar-style animated feature film look, vibrant colors, soft global illumination lighting, "
        "single continuous camera shot, zero scene cuts, zero morphing, zero text, zero signs."
    ),
    "Boneco Palito 2D (Com Boné Azul)": (
        "2D minimalist vector animation, clean flat illustration style, single continuous camera shot, "
        "zero scene cuts, consistent simple white stick figure characters, expressive eyes, zero text, zero letters."
    ),
    "Personalizado (Definir abaixo)": ""
}

def fix_pronunciation(text, lang_label):
    if not text:
        return ""
    t = text.strip()
    if "Português" in lang_label:
        t = re.sub(r'\binscreva[-\s]*on[-\s]*se\b', 'inscreva-se', t, flags=re.IGNORECASE)
        t = re.sub(r'\bEUA\b', 'Estados Unidos', t)
        t = re.sub(r'\bONU\b', 'Organização das Nações Unidas', t)
        t = re.sub(r'\bIBGE\b', 'I B G E', t)
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

def get_strict_voice_lock(gender_choice, lang_label, custom_voice_desc=""):
    lang_en = LANGUAGES[lang_label]["name_en"]
    extra = f" Specific vocal signature: {custom_voice_desc.strip()}." if custom_voice_desc.strip() else ""
    if "Masculina" in gender_choice:
        return (
            f"[STRICT ACOUSTIC VOICEPRINT LOCK: Off-screen studio narration by the EXACT SAME 35-year-old male narrator "
            f"across all scenes. Vocal profile: warm chest-resonant baritone (115 Hz fundamental pitch), crystal-Esse erro `SyntaxError` na linha 418 aconteceu porque o código foi cortado exatamente no meio da frase `if len(out) > 60:` na hora de copiar e colar no GitHub (ficou apenas `if len(out) >` e faltou todo o resto da metade para baixo do arquivo).

Para facilitar e evitar qualquer corte ao selecionar com o mouse, gerei uma versão enxuta e revisada do `app.py` completo abaixo, e você pode copiar com **um único clique** sem arrastar o cursor:

1. Passe o mouse no **canto superior direito da caixa de código abaixo** e clique no **ícone dos dois quadradinhos (Copiar código)** — não selecione arrastando o mouse para não cortar nada.
2. Abra o `app.py` no GitHub, clique no **ícone do lápis**, aperte **`Ctrl + A`** e **`Delete`** para limpar a caixa inteira, aperte **`Ctrl + V`** para colar tudo de uma vez e confira se a última linha lá embaixo termina com `# FIM DO ARQUIVO APP.PY`.
3. Clique no botão verde **Commit changes...** no canto superior direito.

```python
import os
import io
import re
import math
import base64
import shutil
import zipfile
import tempfile
import subprocess
import unicodedata
import requests
import streamlit as st

st.set_page_config(page_title="Estudio Global Google Flow", page_icon="🎬", layout="wide")

@st.cache_resource
def get_ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

DEFAULT_CHAR_A = (
    "52-year-old Brazilian rural father, tanned weathered skin, square jaw, clean-shaven cheeks with a thick "
    "neatly trimmed dark-gray mustache, wearing a beige woven straw hat with a thin brown leather band and "
    "a solid navy-blue cotton button-up shirt with sleeves rolled to the elbows"
)
DEFAULT_CHAR_B = (
    "22-year-old Brazilian young woman, warm olive skin, oval face, expressive dark brown eyes, shoulder-length "
    "defined dark brown curly hair worn loose, wearing a solid mustard-yellow ribbed t-shirt under a classic "
    "medium-blue denim jacket, small silver stud earrings"
)

if "saved_script" not in st.session_state:
    st.session_state["saved_script"] = ""
if "auto_duration_min" not in st.session_state:
    st.session_state["auto_duration_min"] = 1
if "dna_char_a" not in st.session_state:
    st.session_state["dna_char_a"] = DEFAULT_CHAR_A
if "dna_char_b" not in st.session_state:
    st.session_state["dna_char_b"] = DEFAULT_CHAR_B
if "dna_single_char" not in st.session_state:
    st.session_state["dna_single_char"] = ""
if "voice_char_a" not in st.session_state:
    st.session_state["voice_char_a"] = "Deep, gruff, protective 52-year-old rural male baritone voice (105 Hz), calm interior Minas Gerais cadence"
if "voice_char_b" not in st.session_state:
    st.session_state["voice_char_b"] = "Clear, bright, natural 22-year-old young female voice (210 Hz), expressive Brazilian cadence"

LANGUAGES = {
    "🇧🇷 Português (Brasil)": {
        "sr_code": "pt-BR",
        "name_en": "Brazilian Portuguese (pt-BR)",
        "end_keywords": ["grande abraco", "visitaria primeiro", "proximo video", "proximo dossie", "comente aqui", "ate a proxima", "qual dessas", "inscreva se"]
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
        "Photorealistic 4K cinema footage, ARRI Alexa look, 50mm prime lens, shallow depth of field, "
        "single continuous smooth camera shot, zero scene cuts, zero morphing, natural warm lighting. "
        "Zero text overlays, zero banners, zero signs."
    ),
    "Cartoon 3D Pixar": (
        "3D Pixar-style animated feature film look, vibrant colors, soft global illumination lighting, "
        "single continuous camera shot, zero scene cuts, zero morphing, zero text, zero signs."
    ),
    "Boneco Palito 2D (Com Boné Azul)": (
        "2D minimalist vector animation, clean flat illustration style, single continuous camera shot, "
        "zero scene cuts, consistent simple white stick figure characters, expressive eyes, zero text, zero letters."
    ),
    "Personalizado (Definir abaixo)": ""
}

def fix_pronunciation(text, lang_label):
    if not text:
        return ""
    t = text.strip()
    if "Português" in lang_label:
        t = re.sub(r'\binscreva[-\s]*on[-\s]*se\b', 'inscreva-se', t, flags=re.IGNORECASE)
        t = re.sub(r'\bEUA\b', 'Estados Unidos', t)
        t = re.sub(r'\bONU\b', 'Organização das Nações Unidas', t)
        t = re.sub(r'\bIBGE\b', 'I B G E', t)
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

def get_strict_voice_lock(gender_choice, lang_label, custom_voice_desc=""):
    lang_en = LANGUAGES[lang_label]["name_en"]
    extra = f" Specific vocal signature: {custom_voice_desc.strip()}." if custom_voice_desc.strip() else ""
    if "Masculina" in gender_choice:
        return (
            f"[STRICT ACOUSTIC VOICEPRINT LOCK: Off-screen studio narration by the EXACT SAME 35-year-old male narrator "
            f"across all scenes. Vocal profile: warm chest-resonant baritone (115 Hz fundamental pitch), crystal-clear native {lang_en}, "
            f"steady 140 WPM documentary cadence, close-mic Neumann U87 sound, 0.3s clean silence before speaking, ZERO whispers or sighs, "
            f"ZERO background music.{extra} Even if women, children, or elders appear on screen, the voice MUST remain this exact 35-year-old man.]"
        )
    return (
        f"[STRICT ACOUSTIC VOICEPRINT LOCK: Off-screen studio narration by the EXACT SAME 32-year-old female narrator "
        f"across all scenes. Vocal profile: warm smooth mezzo-soprano (195 Hz fundamental pitch), crystal-clear native {lang_en}, "
        f"steady 140 WPM documentary cadence, close-mic Neumann U87 sound, 0.3s clean silence before speaking, ZERO whispers or sighs, "
        f"ZERO background music.{extra} Even if men, children, or elders appear on screen, the voice MUST remain this exact 32-year-old woman.]"
    )

def clean_markdown(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL).strip()
    txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt)
    return re.sub(r"\n?```$", "", txt).strip()

def get_available_groq_models(clean_key, vision_only=False):
    headers_groq = {"Authorization": f"Bearer {clean_key}"}
    try:
        r_m = requests.get("[https://api.groq.com/openai/v1/models](https://api.groq.com/openai/v1/models)", headers=headers_groq, timeout=15)
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

def analyze_character_photo(uploaded_img, api_key):
    clean_key = api_key.strip() if api_key else ""
    if not clean_key:
        return None, "Cole sua chave gratuita da Groq (gsk_...) lá no topo primeiro para analisar a foto!"

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
        "Analyze this character image and write a forensic, ultra-specific physical and clothing description in ONE concise "
        "English sentence (40 to 60 words) designed to lock 100% visual identity across AI video scenes. "
        "Include: exact apparent age, ethnicity/skin tone, face shape, eye details, exact hairstyle/color, exact facial hair "
        "(clean-shaven, mustache only, or beard length), headwear if any, and exact clothing colors, fabrics, collar/sleeve details, "
        "and accessories. Output ONLY the English description without intro text."
    )

    last_err = ""
    if clean_key.startswith("gsk_"):
        headers_groq = {"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"}
        for v_mod in get_available_groq_models(clean_key, vision_only=True)[:4]:
            try:
                r_v = requests.post(
                    "[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)",
                    headers=headers_groq,
                    json={
                        "model": v_mod,
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": vision_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}}
                        ]}],
                        "temperature": 0.1,
                        "max_tokens": 300
                    },
                    timeout=45
                )
                if r_v.status_code == 200:
                    desc = clean_markdown(r_v.json()["choices"][0]["message"]["content"])
                    if len(desc) >= 20:
                        return desc, None
                else:
                    last_err = f"{v_mod}: HTTP {r_v.status_code}"
            except Exception as ex:
                last_err = str(ex)
        return None, f"Não foi possível ler a imagem ({last_err})."

    for model_id in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            g_url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){model_id}:generateContent?key={clean_key}"
            payload = {"contents": [{"parts": [{"text": vision_prompt}, {"inline_data": {"mime_type": mime_type, "data": b64_data}}]}]}
            r_g = requests.post(g_url, json=payload, timeout=45)
            if r_g.status_code == 200:
                desc = clean_markdown(r_g.json()["candidates"][0]["content"]["parts"][0]["text"])
                if len(desc) >= 20:
                    return desc, None
            else:
                last_err = f"HTTP {r_g.status_code}"
        except Exception as ex:
            last_err = str(ex)
    return None, f"Falha ao analisar foto: {last_err}"

def build_duo_reference_card(img_a_file, img_b_file):
    try:
        from PIL import Image
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

def transcribe_uploaded_audio_chunks(audio_path, sr_lang_code, ffmpeg_exe):
    import speech_recognition as sr
    dur = get_audio_duration_sec(audio_path, ffmpeg_exe)
    num_chunks = max(1, math.ceil(dur / 8.0))
    recognizer = sr.Recognizer()
    work_dir = tempfile.mkdtemp()
    blocks = []
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
        blocks.append(f"[{t1} - {t2}]\n[CENA: Single continuous cinematic shot illustrating: {spoken_piece}, characters with mouths closed in silence]\nLOCUÇÃO: {spoken_piece}")
    return "\n\n".join(blocks), dur, num_chunks

def generate_ai_script(title, num_scenes, lang_label, style_choice, audio_mode, char_a_desc="", char_b_desc="", single_char_desc="", api_key=""):
    lang_en = LANGUAGES[lang_label]["name_en"]
    if "Diálogo" in audio_mode:
        prompt_text = (
            f"You are a master Brazilian screenwriter creating an authentic, viral, high-retention dialogue scene.\n"
            f"Story / Situation: '{title}'\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n"
            f"Character A (Fixed Identity): {char_a_desc}\n"
            f"Character B (Fixed Identity): {char_b_desc}\n\n"
            f"CRITICAL CONTINUITY, NATURALNESS & VISUAL LOCK RULES:\n"
            f"1. STRICT PROGRESSIVE MEMORY (ZERO REPEATED QUESTIONS): Track every detail revealed in earlier scenes! Never repeat an already-answered question in later scenes. Advance logically.\n"
            f"2. 100% IDIOMATIC NATIVE SPEECH: Write authentic everyday {lang_en}. Every line MUST have strictly 12 to 17 words.\n"
            f"3. ONE SPEAKER PER 8-SECOND SCENE: Alternate between PERSONAGEM A and PERSONAGEM B.\n"
            f"4. FIXED SETTING LOCK: Keep BOTH characters in the exact same room and lighting across all {num_scenes} scenes.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line, no intro/outro):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Medium two-shot in the exact same room, Character A speaking expressively while Character B listens silently, zero text]\n"
            f"PERSONAGEM A: Authentic natural line in {lang_en} (12-17 words, zero abbreviations)."
        )
    else:
        if single_char_desc.strip():
            char_hint = f"the exact protagonist ({single_char_desc.strip()}) exploring the scenery with mouth closed in silence"
        elif "Palito" in style_choice:
            char_hint = "the white stick figure wearing a solid royal-blue baseball cap exploring the scenery"
        elif "Cartoon" in style_choice:
            char_hint = "the 3D character wearing a solid royal-blue baseball cap and blue jeans exploring the scenery"
        else:
            char_hint = "pure cinematic documentary B-roll of landscapes, nature, or architecture (NO TV host or studio presenter)"

        prompt_text = (
            f"You are a rigorous, fact-checked documentary researcher and scriptwriter.\n"
            f"Topic / Title: '{title}'\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n\n"
            f"STRICT FACTUAL ACCURACY & PRONUNCIATION RULES:\n"
            f"1. 100% VERIFIED REAL FACTS ONLY: Never invent local contests, fake dates, or guessed weights.\n"
            f"2. PRONUNCIATION-FRIENDLY: Write ALL numbers, units, and acronyms spelled out in full words in {lang_en}.\n"
            f"3. TIMING: Every LOCUÇÃO MUST have strictly 14 to 18 words in {lang_en}. Scene {num_scenes} ends with a Call-to-Action.\n"
            f"4. CLEAN VISUALS: Every [CENA: ...] must be a single continuous shot in English featuring {char_hint}, zero text, mouths closed.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Single continuous shot in English, no text/signs, mouths closed]\n"
            f"LOCUÇÃO: Verified narration in {lang_en} (14-18 words, zero abbreviations)."
        )

    clean_key = api_key.strip() if api_key else ""
    if not clean_key:
        return "", "⚠️ Cole sua chave gratuita da Groq (gsk_...) lá no canto superior direito e aperte ENTER!"

    last_error = ""
    temp_val = 0.45 if "Diálogo" in audio_mode else 0.2

    if clean_key.startswith("gsk_"):
        headers_groq = {"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"}
        for groq_model in get_available_groq_models(clean_key)[:6]:
            try:
                r_groq = requests.post(
                    "[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)",
                    headers=headers_groq,
                    json={
                        "model": groq_model,
                        "messages": [
                            {"role": "system", "content": "Output ONLY the requested formatted script scenes. Maintain strict continuity and natural expressions."},
                            {"role": "user", "content": prompt_text}
                        ],
                        "temperature": temp_val,
                        "max_tokens": 7000
                    },
                    timeout=90
                )
                if r_groq.status_code == 200:
                    out = clean_markdown(r_groq.json()["choices"][0]["message"]["content"])
                    if len(out) >= 60:
                        lines_fixed = []
                        for ln in out.splitlines():
                            if re.match(r'^(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|PERSONAGEM\s*[AB12])\s*:', ln.strip(), re.IGNORECASE):
                                prefix, body = ln.split(":", 1)
                                lines_fixed.append(f"{prefix.strip()}: {fix_pronunciation(body, lang_label)}")
                            else:
                                lines_fixed.append(ln)
                        return "\n".join(lines_fixed), None
                else:
                    last_error = f"HTTP {r_groq.status_code}: {r_groq.text[:180]}"
            except Exception as e_g:
                last_error = str(e_g)
        return "", f"❌ Erro na Groq: {last_error}"

    for model_id in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            g_url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){model_id}:generateContent?key={clean_key}"
            r_gem = requests.post(
                g_url,
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt_text}]}], "generationConfig": {"temperature": temp_val}},
                timeout=90
            )
            if r_gem.
