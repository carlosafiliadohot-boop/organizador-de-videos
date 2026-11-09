import os
import re
import shutil
import zipfile
import tempfile
import subprocess
import unicodedata
import urllib.parse
import requests
import streamlit as st
import speech_recognition as sr
from rapidfuzz import fuzz
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

st.set_page_config(page_title="Estudio Global Google Flow", page_icon="🎬", layout="wide")

if "saved_script" not in st.session_state:
    st.session_state["saved_script"] = ""

LANGUAGES = {
    "🇧🇷 Português (Brasil)": {
        "sr_code": "pt-BR",
        "name_en": "Brazilian Portuguese (pt-BR)",
        "end_keywords": ["grande abraco", "visitaria primeiro", "proximo video", "proximo dossie", "comente aqui", "ate a proxima"]
    },
    "🇪🇸 Espanhol (Latino/Neutro)": {
        "sr_code": "es-MX",
        "name_en": "Latin American Spanish (es-419)",
        "end_keywords": ["gran abrazo", "proximo video", "deja tu comentario", "hasta la proxima", "cual elegirias"]
    },
    "🇺🇸 Inglês (EUA)": {
        "sr_code": "en-US",
        "name_en": "American English (en-US)",
        "end_keywords": ["next video", "leave a comment", "let us know in the comments", "thanks for watching", "see you next time"]
    },
    "🇫🇷 Francês (França)": {
        "sr_code": "fr-FR",
        "name_en": "French (fr-FR)",
        "end_keywords": ["prochaine video", "laissez un commentaire", "a bientot", "merci d avoir regarde"]
    },
    "🇮🇹 Italiano (Itália)": {
        "sr_code": "it-IT",
        "name_en": "Italian (it-IT)",
        "end_keywords": ["prossimo video", "lascia un commento", "a presto", "grazie per aver guardato"]
    }
}

STYLE_PRESETS = {
    "Boneco Palito 2D (Com Boné Azul)": (
        "2D minimalist vector animation, clean flat illustration style. "
        "Main character is the EXACT SAME simple white stick figure wearing a blue baseball cap, "
        "expressive eyes, mouth closed and silent (no lip-sync), no on-screen text or letters."
    ),
    "Cartoon 3D Pixar (Boneco Boné Azul)": (
        "3D Pixar-style animated illustration, vibrant colors, soft cinematic lighting. "
        "Main character is the EXACT SAME friendly 3D stylized character wearing a blue baseball cap "
        "and casual jeans, mouth closed and silent (no lip-sync), no on-screen text or signs."
    ),
    "Cinematográfico Realista 4K (Documentário)": (
        "Photorealistic 4K documentary footage, cinematic drone and gimbal camera movement, "
        "natural daylight, ultra-detailed scenery. Any people on screen have "
        "their mouths closed and are silent (no lip-sync), no text overlays or gibberish signs."
    ),
    "Personalizado (Definir abaixo)": ""
}

def get_voice_lock(gender_choice, lang_label):
    lang_en = LANGUAGES[lang_label]["name_en"]
    if "Masculina" in gender_choice:
        return (
            f"[AUDIO & VOICE LOCK: Off-screen studio narration by the EXACT SAME 35-year-old male narrator "
            f"with a warm, deep, clear baritone documentary voice, native {lang_en}, steady 140 WPM pace, "
            f"clean studio condenser microphone, zero vocal variation between scenes. Even if female, elderly, or child "
            f"characters appear on screen, the off-screen voice MUST remain the 35-year-old male baritone narrator.]"
        )
    return (
        f"[AUDIO & VOICE LOCK: Off-screen studio narration by the EXACT SAME 32-year-old female narrator "
        f"with a warm, smooth, clear mezzo-soprano documentary voice, native {lang_en}, steady 140 WPM pace, "
        f"clean studio condenser microphone, zero vocal variation between scenes. Even if male, elderly, or child "
        f"characters appear on screen, the off-screen voice MUST remain the 32-year-old female mezzo-soprano narrator.]"
    )

def format_ts(sec):
    return f"{sec // 60:02d}:{sec % 60:02d}"

def build_fallback_script(title, num_scenes, lang_label):
    blocks = []
    for i in range(num_scenes):
        ts = f"[{format_ts(i * 8)} - {format_ts((i + 1) * 8)}]"
        if i == 0:
            vis = "Wide cinematic aerial shot establishing the main location in bright daylight, characters silent with mouths closed"
            loc = f"Você já parou para descobrir todos os segredos e detalhes por trás de {title} hoje?"
        elif i == num_scenes - 1:
            vis = "Main character smiling and waving goodbye in a clean bright setting, mouth closed and silent"
            loc = "O que você achou dessas informações? Deixe o seu comentário aqui embaixo e até o próximo vídeo!"
        else:
            vis = f"Detailed cinematic scene #{i+1} illustrating {title}, smooth camera movement, characters silent with mouths closed"
            loc = f"No destaque número {i+1} sobre {title}, vemos detalhes que transformam completamente a qualidade de vida local."
        blocks.append(f"{ts}\n[CENA: {vis}]\nLOCUÇÃO: {loc}")
    return "\n\n".join(blocks)

def generate_ai_script(title, minutes, lang_label, style_choice, gemini_key=""):
    num_scenes = max(4, int((minutes * 60) // 8))
    lang_en = LANGUAGES[lang_label]["name_en"]
    prompt_text = (
        f"Write a complete video script about '{title}' with EXACTLY {num_scenes} scenes (8 seconds each).\n"
        f"Format EVERY scene strictly in 3 lines separated by a blank line:\n"
        f"[00:00 - 00:08]\n"
        f"[CENA: Detailed visual description in English, characters with mouths closed in silence]\n"
        f"LOCUÇÃO: Engaging narration written 100% in {lang_en} with 14 to 18 words maximum.\n"
        f"Scene {num_scenes} must end with a Call-to-Action asking viewers to comment below."
    )
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

    if gemini_key and len(gemini_key.strip()) > 10:
        try:
            g_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key.strip()}"
            r_gem = requests.post(g_url, json={"contents": [{"parts": [{"text": prompt_text}]}]}, headers=headers, timeout=90)
            if r_gem.status_code == 200:
                txt = r_gem.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                if len(txt) > 60:
                    return txt
        except Exception:
            pass

    for m_name in ["openai", "mistral"]:
        try:
            r1 = requests.post(
                "https://text.pollinations.ai/openai",
                headers=headers,
                json={"model": m_name, "messages": [{"role": "user", "content": prompt_text}]},
                timeout=75
            )
            if r1.status_code == 200:
                txt = r1.json()["choices"][0]["message"]["content"].strip()
                if len(txt) > 60:
                    return txt
        except Exception:
            pass

    try:
        r2 = requests.post(
            "https://text.pollinations.ai/",
            headers=headers,
            json={"messages": [{"role": "user", "content": prompt_text}], "model": "openai"},
            timeout=75
        )
        if r2.status_code == 200 and len(r2.text.strip()) > 60:
            return r2.text.strip()
    except Exception:
        pass

    return build_fallback_script(title, num_scenes, lang_label)

def extract_scenes_for_prompts(raw_script):
    blocks = re.split(r'\n\s*\n', raw_script.strip())
    scenes = []
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        visual, spoken = "", ""
        for line in lines:
            m_cena = re.search(r'\[?(?:CENA\vert{}SCENE)\s*:\s*(.+?)\]?$', line, re.IGNORECASE)
            m_loc = re.search(r'(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
            if m_cena:
                visual = m_cena.group(1).strip()
            elif m_loc:
                spoken = m_loc.group(1).strip()
            elif not re.match(r'^\[\d+:\d+', line) and not spoken:
                spoken = line
        if spoken or visual:
            if not visual:
                visual = "Detailed cinematic scenery matching the narration, characters with mouths closed in silence"
            scenes.append({"visual": visual, "spoken": spoken})
    return scenes

def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text.lower())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text
