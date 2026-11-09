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
DEFAULT_SINGLE_CHAR = ""

if "saved_script" not in st.session_state:
    st.session_state["saved_script"] = ""
if "auto_duration_min" not in st.session_state:
    st.session_state["auto_duration_min"] = 1
if "dna_char_a" not in st.session_state:
    st.session_state["dna_char_a"] = DEFAULT_CHAR_A
if "dna_char_b" not in st.session_state:
    st.session_state["dna_char_b"] = DEFAULT_CHAR_B
if "dna_single_char" not in st.session_state:
    st.session_state["dna_single_char"] = DEFAULT_SINGLE_CHAR
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
        r_m = requests.get("https://api.groq.com/openai/v1/models", headers=headers_groq, timeout=15)
        if r_m.status_code == 200:
            raw_ids = [m["id"] for m in r_m.json().get("data", []) if "id" in m]
            skip_words = ("whisper", "guard", "tts", "playai", "orpheus", "embed", "safeguard", "allam")
            chat_models = [mid for mid in raw_ids if not any(sw in mid.lower() for sw in skip_words)]

            if vision_only:
                vis_models = [
                    mid for mid in chat_models
                    if any(vk in mid.lower() for vk in ("llama-4", "scout", "maverick", "vision"))
                ]
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
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers_groq,
                    json={
                        "model": v_mod,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": vision_prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}}
                                ]
                            }
                        ],
                        "temperature": 0.1,
                        "max_tokens": 300
                    },
                    timeout=45
                )
                if r_v.status_code == 200:
                    desc = clean_markdown(r_v.json()["choices"][0]["message"]["content"])
                    if len(desc) > 20:
                        return desc, None
                else:
                    last_err = f"{v_mod}: HTTP {r_v.status_code}"
            except Exception as ex:
                last_err = str(ex)
        return None, f"Não foi possível ler a imagem ({last_err})."

    for model_id in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            g_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={clean_key}"
            payload = {
                "contents": [{
                    "parts": [
                        {"text": vision_prompt},
                        {"inline_data": {"mime_type": mime_type, "data": b64_data}}
                    ]
                }]
            }
            r_g = requests.post(g_url, json=payload, timeout=45)
            if r_g.status_code == 200:
                desc = clean_markdown(r_g.json()["candidates"][0]["content"]["parts"][0]["text"])
                if len(desc) > 20:
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
        cmd = [
            ffmpeg_exe, '-y', '-ss', str(start_s), '-i', audio_path,
            '-t', '8.0', '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', wav_chunk
        ]
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
        blocks.append(
            f"[{t1} - {t2}]\n"
            f"[CENA: Single continuous cinematic shot illustrating: {spoken_piece}, characters with mouths closed in silence]\n"
            f"LOCUÇÃO: {spoken_piece}"
        )
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
            f"1. STRICT PROGRESSIVE MEMORY (ZERO REPEATED QUESTIONS): Track every detail revealed in earlier scenes! If a character already said a name (e.g., Lucas), profession, or reason in Scene 3, NEVER ask 'who is he?' or repeat an already-answered question in later scenes. Every line must advance the conversation logically toward a punchline or climax.\n"
            f"2. 100% IDIOMATIC NATIVE SPEECH: Write authentic, natural everyday {lang_en}. NEVER use awkward literal translations (never write unnatural phrases like 'vi o rosto dele na minha cara'). Every line MUST have strictly 12 to 17 words so it finishes comfortably inside 8 seconds.\n"
            f"3. ONE SPEAKER PER 8-SECOND SCENE: Alternate between PERSONAGEM A and PERSONAGEM B. In each scene, ONLY the active speaker moves their lips while the other listens silently.\n"
            f"4. FIXED SETTING LOCK: Define ONE exact room/location (e.g., cozy Minas Gerais rustic kitchen with wood-burning stove in soft daylight) and keep BOTH characters in that exact same room, position, and lighting across all {num_scenes} scenes.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line, no intro/outro):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Medium two-shot in the exact same rustic kitchen, Character A speaking expressively while Character B listens silently, zero text]\n"
            f"PERSONAGEM A: Authentic, natural line in {lang_en} (12-17 words, zero abbreviations)."
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
            f"1. 100% VERIFIED REAL FACTS ONLY: Every fact, place, record, or curiosity MUST be 100% true and verifiable. NEVER invent local contests, fake dates, or guessed weights.\n"
            f"2. PRONUNCIATION-FRIENDLY: Write ALL numbers, units, and acronyms spelled out in full words in {lang_en} (write 'quilos' not 'kg', 'Estados Unidos' not 'EUA').\n"
            f"3. TIMING: Every LOCUÇÃO MUST have strictly 14 to 18 words in {lang_en}. Scene {num_scenes} ends with a clear Call-to-Action asking viewers to comment.\n"
            f"4. CLEAN VISUALS: Every [CENA: ...] must be a single continuous shot in English featuring {char_hint}, zero text/banners, all mouths closed in silence.\n\n"
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
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers_groq,
                    json={
                        "model": groq_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Output ONLY the requested formatted script scenes. Maintain strict logical continuity across dialogue turns and use 100% natural idiomatic expressions."
                            },
                            {"role": "user", "content": prompt_text}
                        ],
                        "temperature": temp_val,
                        "max_tokens": 7000
                    },
                    timeout=90
                )
                if r_groq.status_code == 200:
                    out = clean_markdown(r_groq.json()["choices"][0]["message"]["content"])
                    if len(out) > 60:
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
            g_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={clean_key}"
            r_gem = requests.post(
                g_url,
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt_text}]}], "generationConfig": {"temperature": temp_val}},
                timeout=90
            )
            if r_gem.status_code == 200:
                out = clean_markdown(r_gem.json()["candidates"][0]["content"]["parts"][0]["text"])
                if len(out) > 60:
                    return out, None
            else:
                last_error = f"HTTP {r_gem.status_code}: {r_gem.text[:180]}"
        except Exception as e_req:
            last_error = str(e_req)

    return "", f"❌ Falha na chave ({last_error}). Use sua chave 'gsk_...' da Groq!"

def extract_scenes_for_prompts(raw_script, lang_label):
    blocks = re.split(r'\n\s*\n', raw_script.strip())
    scenes = []
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        visual, spoken, speaker_tag = "", "", "NARRATOR"
        for line in lines:
            m_cena = re.search(r'\[?(?:CENA|SCENE)\s*:\s*(.+?)\]?$', line, re.IGNORECASE)
            m_pa = re.search(r'^PERSONAGEM\s*(?:A|1)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
            m_pb = re.search(r'^PERSONAGEM\s*(?:B|2)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
            m_loc = re.search(r'^(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)

            if m_cena:
                visual = m_cena.group(1).strip()
            elif m_pa:
                speaker_tag = "A"
                spoken = fix_pronunciation(m_pa.group(1).strip(), lang_label)
            elif m_pb:
                speaker_tag = "B"
                spoken = fix_pronunciation(m_pb.group(1).strip(), lang_label)
            elif m_loc:
                speaker_tag = "NARRATOR"
                spoken = fix_pronunciation(m_loc.group(1).strip(), lang_label)
            elif not re.match(r'^\[\d+:\d+', line) and not spoken:
                spoken = fix_pronunciation(line, lang_label)

        if spoken or visual:
            if not visual:
                visual = "Single continuous wide cinematic shot matching the context, zero text on screen"
            scenes.append({"visual": visual, "spoken": spoken, "speaker": speaker_tag})
    return scenes

def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text.lower())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_script_text(raw, lang_label):
    spoken_lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r'^(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala|PERSONAGEM\s*[AB12])\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
        if m:
            spoken_lines.append(fix_pronunciation(m.group(1).strip(), lang_label))
        elif not re.match(r'^\[\d+:\d+', line) and not re.match(r'^\[(?:CENA|SCENE):', line, re.IGNORECASE):
            cleaned = re.sub(r'\[(?:CENA|SCENE):.*?\]', '', line, flags=re.IGNORECASE).strip()
            if cleaned:
                spoken_lines.append(fix_pronunciation(cleaned, lang_label))
    full_spoken = ' '.join(spoken_lines) if spoken_lines else raw
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

st.title("🎬 Estúdio Completo Google Flow — Upload de Personagens, Voz Fixa & Diálogos")

secret_key = ""
try:
    secret_key = st.secrets.get("API_KEY", "") or st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    secret_key = ""

col_top1, col_top2 = st.columns([2, 1])
with col_top1:
    selected_lang = st.selectbox("🌍 Idioma do Projeto:", list(LANGUAGES.keys()))
with col_top2:
    api_key_input = st.text_input(
        "🔑 Chave IA Grátis (Groq 'gsk_...' ou Google):",
        value=secret_key,
        type="password",
        placeholder="Cole sua chave gsk_... e aperte ENTER"
    )

tab1, tab2 = st.tabs(["📝 1. Personagens, Roteiro IA & Prompts", "🎞️ 2. Organizador & Mixagem de Áudio Próprio"])

with tab1:
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
                mute_flow_for_custom = st.checkbox("Gerar vídeos mudos no Flow", value=False, help="Deixe desmarcado para a Aba 2 organizar os vídeos pela voz-guia antes de trocar pelo seu áudio!")
                if ref_audio_file is not None:
                    if st.button("🎧 LER MEU ÁUDIO E MONTAR ROTEIRO DE 8 EM 8 SEGUNDOS", use_container_width=True):
                        with st.spinner("Transcrevendo seu áudio em blocos de 8 segundos..."):
                            ffmpeg_exe = get_ffmpeg()
                            tmp_aud = os.path.join(tempfile.mkdtemp(), ref_audio_file.name)
                            with open(tmp_aud, "wb") as fa:
                                fa.write(ref_audio_file.getbuffer())
                            t_script, dur_s, n_sc = transcribe_uploaded_audio_chunks(tmp_aud, LANGUAGES[selected_lang]["sr_code"], ffmpeg_exe)
                            st.session_state["saved_script"] = t_script
                            st.success(f"✅ Áudio transcrito ({dur_s:.1f}s -> {n_sc} cenas)!")

        with cm2:
            up_single = st.file_uploader("📸 Opcional: Subir Foto do Personagem Fixo (Ex: Mineirinho / Mascote):", type=["png", "jpg", "jpeg", "webp"], key="up_single")
            if up_single is not None:
                has_ref_image = True
                st.image(up_single, width=140, caption="Personagem de Referência")
                if st.button("🔍 EXTRAIR DNA FÍSICO DA FOTO (IA)", key="btn_single_dna", use_container_width=True):
                    with st.spinner("Analisando cada detalhe do rosto e roupa na foto..."):
                        dna_res, err_v = analyze_character_photo(up_single, api_key_input)
                        if err_v:
                            st.error(err_v)
                        else:
                            st.session_state["dna_single_char"] = dna_res
                            st.success("✅ DNA visual extraído e travado!")
            st.text_area("🧬 DNA Físico Fixo do Protagonista (Opcional — em Inglês):", key="dna_single_char", height=90, placeholder="Deixe vazio para documentário de paisagens ou suba uma foto acima...")

    elif "Modo 2" in audio_mode:
        st.info("💡 **Trava Dupla de Identidade:** Você pode subir a foto do Personagem A e do Personagem B abaixo! A IA lê a foto para travar a roupa e o rosto no prompt, e ainda gera um **Cartão Duplo 16:9** pronto para você anexar como *Referência/Ingredient* lá no Google Flow.")
        up_col1, up_col2 = st.columns([1, 1])
        with up_col1:
            up_char_a = st.file_uploader("📸 Subir Foto do Personagem A (Opcional):", type=["png", "jpg", "jpeg", "webp"], key="up_a")
            if up_char_a is not None:
                has_ref_image = True
                st.image(up_char_a, width=150, caption="Foto Personagem A")
        with up_col2:
            up_char_b = st.file_uploader("📸 Subir Foto do Personagem B (Opcional):", type=["png", "jpg", "jpeg", "webp"], key="up_b")
            if up_char_b is not None:
                has_ref_image = True
                st.image(up_char_b, width=150, caption="Foto Personagem B")

        if up_char_a is not None or up_char_b is not None:
            b_col1, b_col2 = st.columns([1, 1])
            with b_col1:
                if st.button("🔍 EXTRAIR DNA FÍSICO E ROUPAS DAS FOTOS ENVIADAS (IA)", type="primary", use_container_width=True):
                    with st.spinner("Lendo traços faciais, cabelo e roupas exatas nas fotos..."):
                        if up_char_a is not None:
                            dna_a, err_a = analyze_character_photo(up_char_a, api_key_input)
                            if err_a:
                                st.error(f"Foto A: {err_a}")
                            else:
                                st.session_state["dna_char_a"] = dna_a
                        if up_char_b is not None:
                            dna_b, err_b = analyze_character_photo(up_char_b, api_key_input)
                            if err_b:
                                st.error(f"Foto B: {err_b}")
                            else:
                                st.session_state["dna_char_b"] = dna_b
                        st.success("✅ DNA físico extraído das fotos com precisão milimétrica!")
            with b_col2:
                duo_png = build_duo_reference_card(up_char_a, up_char_b)
                if duo_png:
                    st.download_button(
                        "🖼️ Baixar Cartão 16:9 dos Personagens (Para subir no Google Flow)",
                        data=duo_png,
                        file_name="Referencia_Personagens_Flow_16x9.png",
                        mime="image/png",
                        use_container_width=True
                    )

        cd1, cd2 = st.columns([1, 1])
        with cd1:
            st.text_area("👤 DNA Físico e Roupa Fixa — Personagem A:", key="dna_char_a", height=110)
            st.text_input("🎙️ Trava de Voz — Personagem A:", key="voice_char_a")
        with cd2:
            st.text_area("👤 DNA Físico e Roupa Fixa — Personagem B:", key="dna_char_b", height=110)
            st.text_input("🎙️ Trava de Voz — Personagem B:", key="voice_char_b")

    st.divider()
    st.markdown("### 🤖 Passo 2: Gerar Roteiro com Memória de Continuidade")
    col_t1, col_t2, col_t3 = st.columns([3, 1, 1])
    with col_t1:
        video_title = st.text_input("Título, Tema ou Situação do Diálogo:", placeholder="Ex: Pai caipira descobrindo o namorado da filha / 5 Cidades de MG")
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
                with st.spinner(f"Criando roteiro de {total_scenes_calc} cenas com continuidade travada..."):
                    script_out, err_msg = generate_ai_script(
                        video_title,
                        total_scenes_calc,
                        selected_lang,
                        style_choice,
                        audio_mode,
                        st.session_state.get("dna_char_a", ""),
                        st.session_state.get("dna_char_b", ""),
                        st.session_state.get("dna_single_char", ""),
                        api_key_input
                    )
                    if err_msg:
                        st.error(err_msg)
                    else:
                        st.session_state["saved_script"] = script_out
                        st.success("✅ Roteiro pronto e sem repetição de perguntas!")

    with cs2:
        script_for_prompts = st.text_area("Roteiro Completo (Editável):", value=st.session_state["saved_script"], height=260)

    if st.button("✨ GERAR TODOS OS PROMPTS BLINDADOS PARA O GOOGLE FLOW", type="primary", use_container_width=True):
        if not script_for_prompts.strip():
            st.warning("Gere ou cole um roteiro primeiro.")
        else:
            st.session_state["saved_script"] = script_for_prompts
            scenes = extract_scenes_for_prompts(script_for_prompts, selected_lang)
            visual_anchor = custom_style if style_choice == "Personalizado (Definir abaixo)" else STYLE_PRESETS[style_choice]
            lang_en_name = LANGUAGES[selected_lang]["name_en"]
            ref_tag = "Match 100% the uploaded reference character image(s) in face, hair, and exact outfit. " if has_ref_image else ""

            st.success(f"✅ {len(scenes)} Prompts gerados! Copie abaixo ou baixe o arquivo .TXT.")
            all_prompts_text = []

            for idx, sc in enumerate(scenes, 1):
                if "Modo 2" in audio_mode:
                    is_a = (sc["speaker"] != "B")
                    active_char = "Character A" if is_a else "Character B"
                    silent_char = "Character B" if is_a else "Character A"
                    active_voice = st.session_state.get("voice_char_a", "") if is_a else st.session_state.get("voice_char_b", "")
                    dna_a_txt = st.session_state.get("dna_char_a", DEFAULT_CHAR_A)
                    dna_b_txt = st.session_state.get("dna_char_b", DEFAULT_CHAR_B)

                    p_box = (
                        f"[VISUAL & WARDROBE DNA LOCK: {visual_anchor} {ref_tag}"
                        f"Character A MUST ALWAYS be: {dna_a_txt} (NEVER change shirt color, hat, or facial hair). "
                        f"Character B MUST ALWAYS be: {dna_b_txt} (NEVER change hairstyle, face, or outfit colors). "
                        f"Single continuous 8-second camera shot, same exact room lighting, zero cuts, zero text on screen.]\n"
                        f"SCENE ACTION: {sc['visual']}. ONLY {active_char} moves their mouth with natural realistic lip-sync while {silent_char} keeps mouth completely closed listening.\n"
                        f"[DIALOGUE VOICEPRINT LOCK: {active_char} speaks with {active_voice}, native {lang_en_name}. "
                        f"Start with 0.3s clean silence, ZERO whispers before speaking, ZERO background music.] "
                        f"{active_char} says clearly in {lang_en_name}: \"{sc['spoken']}\""
                    )
                elif "Modo 3" in audio_mode and mute_flow_for_custom:
                    single_dna = st.session_state.get("dna_single_char", "").strip()
                    char_clause = f"Protagonist DNA Lock: {single_dna}. " if single_dna else ""
                    p_box = (
                        f"[VISUAL STYLE & CAMERA LOCK: {visual_anchor} {ref_tag}{char_clause}"
                        f"CRITICAL RULE: Single continuous 8-second shot, zero cuts. All characters keep mouths closed in silence. Zero text on screen.]\n"
                        f"SCENE ACTION: {sc['visual']}.\n"
                        f"[AUDIO LOCK: Completely silent ambient track, zero speech, zero narration, zero music.]"
                    )
                else:
                    single_dna = st.session_state.get("dna_single_char", "").strip()
                    char_clause = f"Protagonist DNA Lock: {single_dna}. " if single_dna else ""
                    voice_anchor = get_strict_voice_lock(voice_choice, selected_lang, custom_voice_timbre)
                    p_box = (
                        f"[VISUAL STYLE & CAMERA LOCK: {visual_anchor} {ref_tag}{char_clause}"
                        f"CRITICAL RULE: Single continuous 8-second camera shot, zero cuts, zero morphing. "
                        f"All people on screen MUST keep their mouths closed and silent (strictly no lip-sync). Zero text, zero signs, zero banners.]\n"
                        f"SCENE ACTION: {sc['visual']}.\n"
                        f"{voice_anchor} Narrator says clearly in {lang_en_name}: \"{sc['spoken']}\""
                    )

                all_prompts_text.append(f"=== CENA {idx:03d} ===\n{p_box}\n")
                with st.expander(f"🎬 Cena {idx:03d} ({sc['speaker']}) — \"{sc['spoken'][:60]}...\"", expanded=(idx <= 3)):
                    st.code(p_box, language="text")

            st.download_button("📥 Baixar Todos os Prompts (.TXT)", data="\n".join(all_prompts_text), file_name="Prompts_Flow.txt", use_container_width=True)

with tab2:
    st.subheader(f"Organizador por Voz & Mixagem de Áudio Próprio ({selected_lang})")
    col1, col2 = st.columns([1, 1])

    with col1:
        roteiro_input = st.text_area("📜 1. Roteiro Completo do Vídeo:", value=st.session_state["saved_script"], height=280)

    with col2:
        uploaded_files = st.file_uploader(
            "📦 2. Envie o .ZIP do Google Flow (ou vários .MP4):",
            type=["zip", "mp4"],
            accept_multiple_files=True
        )
        st.markdown("#### 🎧 3. Substituir pelo Seu Próprio Áudio (Opcional)")
        master_custom_audio = st.file_uploader(
            "Se quiser trocar o som do vídeo pela sua própria locução/música (.mp3, .wav, .m4a), envie aqui:",
            type=["mp3", "wav", "m4a", "ogg"]
        )
        sort_method = st.radio(
            "Como ordenar os clipes antes de juntar?",
            ["🗣️ Escutar a fala dos clipes e ordenar pelo roteiro (Automático)", "🔢 Ordenar apenas pelo nome dos arquivos (Para vídeos gerados mudos)"],
            horizontal=False
        )

    if st.button("🚀 ORGANIZAR CENAS E GERAR VÍDEO FINAL", type="primary", use_container_width=True):
        if not uploaded_files:
            st.error("Envie o ficheiro .ZIP ou os vídeos .MP4.")
        elif "Escutar" in sort_method and (not roteiro_input or len(roteiro_input.strip()) < 10):
            st.error("Cole o roteiro à esquerda (ou mude para ordenar pelo nome dos arquivos se os vídeos forem mudos).")
        else:
            import speech_recognition as sr
            ffmpeg_exe = get_ffmpeg()
            work_dir = tempfile.mkdtemp()
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
                                    mp4_files.append(t_path)
                elif uf.name.lower().endswith(".mp4"):
                    t_path = os.path.join(extract_dir, uf.name)
                    with open(t_path, "wb") as f:
                        f.write(uf.getbuffer())
                    mp4_files.append(t_path)

            if not mp4_files:
                st.error("Nenhum vídeo .MP4 encontrado.")
            else:
                results = []
                p_bar = st.progress(0, text="Processando cenas...")
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
                        results.append({'path': v_path, 'original_name': fn, 'transcript': tr, 'position': pos})
                        p_bar.progress(idx / total, text=f"Escutando cena {idx}/{total}: '{tr[:45]}...'")
                    results.sort(key=lambda x: (x['position'], x['original_name']))
                else:
                    mp4_files.sort(key=lambda p: os.path.basename(p).lower())
                    for idx, v_path in enumerate(mp4_files, 1):
                        results.append({'path': v_path, 'original_name': os.path.basename(v_path), 'transcript': '(Ordenado por nome)', 'position': idx})
                        p_bar.progress(idx / total, text=f"Preparando cena {idx}/{total}...")

                c_list = os.path.join
