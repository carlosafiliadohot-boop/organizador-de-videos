import os
import re
import time
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

st.set_page_config(
    page_title="Estúdio Global Google Flow",
    page_icon="🎬",
    layout="wide"
)

if "saved_script" not in st.session_state:
    st.session_state["saved_script"] = ""

LANGUAGES = {
    "🇧🇷 Português (Brasil)": {
        "sr_code": "pt-BR",
        "name_en": "Brazilian Portuguese (pt-BR)",
        "name_pt": "Português do Brasil",
        "end_keywords": ["grande abraco", "visitaria primeiro", "proximo video", "proximo dossie", "comente aqui", "ate a proxima"]
    },
    "🇪🇸 Espanhol (Latino/Neutro)": {
        "sr_code": "es-MX",
        "name_en": "Latin American Spanish (es-419)",
        "name_pt": "Espanhol Latino-Americano",
        "end_keywords": ["gran abrazo", "proximo video", "deja tu comentario", "hasta la proxima", "cual elegirias"]
    },
    "🇺🇸 Inglês (EUA)": {
        "sr_code": "en-US",
        "name_en": "American English (en-US)",
        "name_pt": "Inglês Americano",
        "end_keywords": ["next video", "leave a comment", "let us know in the comments", "thanks for watching", "see you next time"]
    },
    "🇫🇷 Francês (França)": {
        "sr_code": "fr-FR",
        "name_en": "French (fr-FR)",
        "name_pt": "Francês",
        "end_keywords": ["prochaine video", "laissez un commentaire", "a bientot", "merci d avoir regarde"]
    },
    "🇮🇹 Italiano (Itália)": {
        "sr_code": "it-IT",
        "name_en": "Italian (it-IT)",
        "name_pt": "Italiano",
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
    else:
        return (
            f"[AUDIO & VOICE LOCK: Off-screen studio narration by the EXACT SAME 32-year-old female narrator "
            f"with a warm, smooth, clear mezzo-soprano documentary voice, native {lang_en}, steady 140 WPM pace, "
            f"clean studio condenser microphone, zero vocal variation between scenes. Even if male, elderly, or child "
            f"characters appear on screen, the off-screen voice MUST remain the 32-year-old female mezzo-soprano narrator.]"
        )

def format_timestamp(sec):
    m = sec // 60
    s = sec % 60
    return f"{m:02d}:{s:02d}"

def build_fallback_script(title, num_scenes, lang_label):
    blocks = []
    for i in range(num_scenes):
        t_start = format_timestamp(i * 8)
        t_end = format_timestamp((i + 1) * 8)
        if i == 0:
            vis = "Wide cinematic aerial drone shot establishing the main location in bright daylight, characters on screen with mouths closed in silence"
            if "Português" in lang_label:
                loc = f"Você já parou para descobrir todos os segredos e detalhes por trás de {title} hoje?"
            elif "Espanhol" in lang_label:
                loc = f"¿Alguna vez te has detenido a descubrir todos los secretos y detalles sobre {title}?"
            elif "Inglês" in lang_label:
                loc = f"Have you ever stopped to discover all the hidden secrets and details behind {title}?"
            elif "Francês" in lang_label:
                loc = f"Avez-vous déjà pris le temps de découvrir tous les secrets cachés derrière {title} ?"
            else:
                loc = f"Ti sei mai fermato a scoprire tutti i segreti e i dettagli nascosti dietro {title}?"
        elif i == num_scenes - 1:
            vis = "Main character smiling and waving goodbye in a clean bright setting, mouth closed and silent"
            if "Português" in lang_label:
                loc = "O que você achou dessas informações? Deixe o seu comentário aqui embaixo e até o próximo vídeo!"
            elif "Espanhol" in lang_label:
                loc = "¿Qué te pareció esta información? ¡Deja tu comentario aquí abajo y hasta el próximo video!"
            elif "Inglês" in lang_label:
                loc = "What did you think about these details? Leave your comment down below and see you next video!"
            elif "Francês" in lang_label:
                loc = "Qu'avez-vous pensé de ces détails ? Laissez votre commentaire ci-dessous et à la prochaine vidéo !"
            else:
                loc = "Cosa ne pensi di questi dettagli? Lascia un commento qui sotto e al prossimo video!"
        else:
            vis = f"Detailed cinematic scene #{i+1} illustrating {title}, smooth camera movement, characters silent with mouths closed"
            if "Português" in lang_label:
                loc = f"Na parte número {i+1} sobre {title}, vemos como cada detalhe transforma completamente a experiência local."
            elif "Espanhol" in lang_label:
                loc = f"En la parte número {i+1} sobre {title}, vemos cómo cada detalle transforma toda la experiencia."
            elif "Inglês" in lang_label:
                loc = f"In part number {i+1} about {title}, we see how every detail transforms the entire experience."
            elif "Francês" in lang_label:
                loc = f"Dans la partie numéro {i+1} sur {title}, nous voyons comment chaque détail transforme l'expérience."
            else:
                loc = f"Nella parte numero {i+1} su {title}, vediamo come ogni dettaglio trasforma l'intera esperienza."

        blocks.append(f"[{t_start} - {t_end}]\n[CENA: {vis}]\nLOCUÇÃO: {loc}")
    return "\n\n".join(blocks)

def generate_ai_script(title, minutes, lang_label, style_choice, gemini_key=""):
    num_scenes = max(4, int((minutes * 60) // 8))
    lang_info = LANGUAGES[lang_label]

    prompt_text = (
        f"You are an expert documentary and viral video scriptwriter.\n"
        f"Write a complete video script about: '{title}'.\n"
        f"Total scenes required: EXACTLY {num_scenes} scenes (each scene is 8 seconds long, totaling {minutes} minute(s)).\n"
        f"Visual style context: {style_choice}.\n\n"
        f"CRITICAL FORMATTING RULES:\n"
        f"1. Follow this exact 3-line structure for EVERY scene, separated by a blank line:\n"
        f"[00:00 - 00:08]\n"
        f"[CENA: Detailed visual description in English showing the scene action, characters with mouths closed in silence]\n"
        f"LOCUÇÃO: Engaging narration written 100% in {lang_info['name_en']} with 14 to 18 words maximum.\n\n"
        f"2. Every LOCUÇÃO line MUST be in {lang_info['name_en']} and have between 14 and 18 words so it fits cleanly inside 8 seconds.\n"
        f"3. Scene {num_scenes} (the final scene) MUST end with a warm Call-to-Action asking viewers to comment below.\n"
        f"4. Output ONLY the script blocks, without any intro or outro remarks."
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "*/*"
    }

    # 1. Se o utilizador colocou uma chave gratuita do Gemini (Google AI Studio)
    if gemini_key and len(gemini_key.strip()) > 10:
        try:
            g_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key.strip()}"
            g_payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
            r_gem = requests.post(g_url, json=g_payload, headers=headers, timeout=90)
            if r_gem.status_code == 200:
                data = r_gem.json()
                text_out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if len(text_out) > 60:
                    return text_out
        except Exception:
            pass

    # 2. Tentativa via Pollinations OpenAI Endpoint com User-Agent de navegador
    for model_name in ["openai", "mistral", "llama"]:
        try:
            r1 = requests.post(
                "https://text.pollinations.ai/openai",
                headers=headers,
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "You are a professional video scriptwriter."},
                        {"role": "user", "content": prompt_text}
                    ],
                    "temperature": 0.7
                },
                timeout=75
            )
            if r1.status_code == 200:
                res_json = r1.json()
                content = res_json["choices"][0]["message"]["content"].strip()
                if len(content) > 60 and "LOCU" in content.upper():
                    return content
        except Exception:
            pass

    # 3. Tentativa via Pollinations Direct POST
    try:
        r2 = requests.post(
            "https://text.pollinations.ai/",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": prompt_text}
                ],
                "model": "openai"
            },
            timeout=75
        )
        if r2.status_code == 200 and len(r2.text.strip()) > 60 and "LOCU" in r2.text.upper():
            return r2.text.strip()
    except Exception:
        pass

    # 4. Tentativa via GET compacto
    try:
        short_prompt = (
            f"Write a {num_scenes}-scene script about {title}. "
            f"Format each scene as:\n[00:00 - 00:08]\n[CENA: visual in English, mouth closed]\n"
            f"LOCUÇÃO: 16 words in {lang_info['name_en']}."
        )
        encoded = urllib.parse.quote(short_prompt)
        r3 = requests.get(f"https://text.pollinations.ai/{encoded}?model=openai", headers=headers, timeout=75)
        if r3.status_code == 200
