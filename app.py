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
if
