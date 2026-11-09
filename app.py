import os
import re
import math
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

if "saved_script" not in st.session_state:
    st.session_state["saved_script"] = ""
if "auto_duration_min" not in st.session_state:
    st.session_state["auto_duration_min"] = 1

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
    "Boneco Palito 2D (Com Boné Azul)": (
        "2D minimalist vector animation, clean flat illustration style. "
        "Single continuous camera shot, zero scene cuts, zero morphing. "
        "Consistent simple white stick figure characters, expressive eyes, zero text, zero banners, zero letters."
    ),
    "Cartoon 3D Pixar (Boneco Boné Azul)": (
        "3D Pixar-style animated illustration, vibrant colors, soft cinematic lighting. "
        "Single continuous camera shot, zero scene cuts, zero morphing. "
        "Consistent stylized 3D characters, zero text, zero banners, zero signs."
    ),
    "Cinematográfico Realista 4K": (
        "Photorealistic 4K cinema footage, single continuous smooth gimbal or drone camera movement, "
        "zero scene cuts, zero morphing, natural daylight, ultra-detailed scenery. "
        "Zero text overlays, zero banners, zero ribbons, zero signs."
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
            f"steady 140 WPM documentary cadence, close-mic Neumann U87 condenser sound, dry studio acoustics, ZERO background music, "
            f"ZERO pitch shift or accent drift.{extra} Even if women, children, or elders appear on screen, the voice MUST remain this exact 35-year-old man.]"
        )
    return (
        f"[STRICT ACOUSTIC VOICEPRINT LOCK: Off-screen studio narration by the EXACT SAME 32-year-old female narrator "
        f"across all scenes. Vocal profile: warm smooth mezzo-soprano (195 Hz fundamental pitch), crystal-clear native {lang_en}, "
        f"steady 140 WPM documentary cadence, close-mic Neumann U87 condenser sound, dry studio acoustics, ZERO background music, "
        f"ZERO pitch shift or accent drift.{extra} Even if men, children, or elders appear on screen, the voice MUST remain this exact 32-year-old woman.]"
    )

def get_audio_duration_sec(audio_path, ffmpeg_exe):
    res = subprocess.run([ffmpeg_exe, '-i', audio_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return 60.0

def transcribe_Uploaded_Audio_Chunks(audio_path, sr_lang_code, ffmpeg_exe):
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

def clean_markdown(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL).strip()
    txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt)
    return re.sub(r"\n?```$", "", txt).strip()

def get_available_groq_models(clean_key):
    headers_groq = {"Authorization": f"Bearer {clean_key}"}
    try:
        r_m = requests.get("https://api.groq.com/openai/v1/models", headers=headers_groq, timeout=15)
        if r_m.status_code == 200:
            raw_ids = [m["id"] for m in r_m.json().get("data", []) if "id" in m]
            skip_words = ("whisper", "guard", "tts", "playai", "orpheus", "embed", "safeguard", "allam")
            chat_models = [mid for mid in raw_ids if not any(sw in mid.lower() for sw in skip_words)]

            def rank_model(m_id):
                ml = m_id.lower()
                if "llama-4" in ml or "maverick" in ml or "scout" in ml:
                    return 0
                if "70b" in ml or "qwen" in ml:
                    return 1
                if "llama" in ml:
                    return 2
                if "deepseek" in ml or "gemma" in ml or "kimi" in ml:
                    return 3
                return 4

            chat_models.sort(key=rank_model)
            if chat_models:
                return chat_models
    except Exception:
        pass
    return ["meta-llama/llama-4-scout-17b-16e-instruct", "qwen-qwq-32b", "gemma2-9b-it"]

def generate_ai_script(title, num_scenes, lang_label, style_choice, audio_mode, char_a_desc="", char_b_desc="", api_key=""):
    lang_en = LANGUAGES[lang_label]["name_en"]

    if "Diálogo" in audio_mode:
        prompt_text = (
            f"You are an expert screenwriter creating a viral, natural, high-retention dialogue video.\n"
            f"Topic / Story: '{title}'\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n"
            f"Character A profile: {char_a_desc}\n"
            f"Character B profile: {char_b_desc}\n\n"
            f"MANDATORY DIALOGUE & VISUAL RULES:\n"
            f"1. ONE SPEAKER PER 8-SECOND SCENE (for clean lip-sync and audio sorting): Alternate naturally between PERSONAGEM A and PERSONAGEM B across scenes. In each scene, ONLY the active speaker moves their lips naturally while the other listens silently.\n"
            f"2. NATURAL SPEECH & TIMING: Write 100% in natural spoken {lang_en}, strictly 13 to 18 words per scene so it fits cleanly inside 8 seconds. Spell out numbers and abbreviations in full words.\n"
            f"3. CONSISTENT VISUALS: Every [CENA: ...] must be in English, describing both or the active character in the setting, single continuous camera shot, zero on-screen text.\n"
            f"4. ENDING: Scene {num_scenes} ends with an engaging hook/CTA to the audience.\n\n"
            f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line, no intro/outro):\n"
            f"[00:00 - 00:08]\n"
            f"[CENA: Single continuous shot in English showing Character A speaking with natural lip-sync while Character B listens, zero text]\n"
            f"PERSONAGEM A: Natural dialogue line in {lang_en} (13-18 words)."
        )
    else:
        char_hint = (
            "the white stick figure with a blue cap exploring the scenery" if "Palito" in style_choice
            else ("the 3D character with a blue cap exploring the scenery" if "Cartoon" in style_choice
                  else "pure cinematic documentary B-roll of landscapes, nature, or architecture (NO TV host or studio presenter)")
        )
        prompt_text = (
            f"You are a rigorous, fact-checked documentary researcher and scriptwriter.\n"
            f"Topic / Title: '{title}'\n"
            f"Total Scenes: Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n\n"
            f"STRICT FACTUAL ACCURACY & PRONUNCIATION RULES:\n"
            f"1. 100% VERIFIED REAL FACTS ONLY: Every fact, place, record, or curiosity MUST be 100% true and verifiable. NEVER invent local contests, fake dates, or guessed weights.\n"
            f"2. PRONUNCIATION-FRIENDLY: Write ALL numbers, units, and acronyms spelled out in full words in
