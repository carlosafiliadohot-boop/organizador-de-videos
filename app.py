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
    temp_val = 0.55 if "Diálogo" in audio_mode else 0.2

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
                            {"role": "system", "content": "Output ONLY the requested formatted script scenes. Spell out abbreviations in full words."},
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

st.title("🎬 Estúdio Completo Google Flow — Voz Fixa, Diálogos & Áudio Próprio")

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

tab1, tab2 = st.tabs(["📝 1. Roteiro, Diálogos, Áudio Próprio & Prompts", "🎞️ 2. Organizador & Mixagem de Áudio Próprio"])

with tab1:
    st.markdown("### 🎛️ Passo 1: Escolha o Modo de Áudio e Atuação")
    audio_mode = st.radio(
        "Como será o áudio deste vídeo?",
        [
            "🎙️ Modo 1: Narrador Fixo (Trava Absoluta da Mesma Voz do Início ao Fim)",
            "🗣️ Modo 2: Diálogo Entre Personagens (Personagens conversando com Lip-Sync e Vozes Fixas)",
            "🎧 Modo 3: Usar Meu Próprio Áudio Gravado (.MP3 / .WAV — Cenas mudas ou guia + substituição na montagem)"
        ]
    )

    char_a_desc, char_b_desc = "", ""
    voice_choice = "🎙️ Voz Masculina Fixa (Locutor Documentário)"
    custom_voice_timbre = ""
    mute_flow_for_custom = False

    if "Modo 1" in audio_mode:
        cm1, cm2 = st.columns([1, 1])
        with cm1:
            voice_choice = st.radio("Gênero da Voz Fixa:", ["🎙️ Voz Masculina Fixa (Barítono 35 anos)", "🎙️ Voz Feminina Fixa (Mezzo-Soprano 32 anos)"])
        with cm2:
            custom_voice_timbre = st.text_input(
                "Detalhe extra da voz (Opcional - trava ainda mais o mesmo timbre):",
                placeholder="Ex: Sotaque mineiro calmo e acolhedor / Locutor sério estilo Discovery"
            )

    elif "Modo 2" in audio_mode:
        cd1, cd2 = st.columns([1, 1])
        with cd1:
            char_a_desc = st.text_input(
                "👤 Personagem A (Aparência + Voz Fixa em Inglês ou PT):",
                value="50-year-old Brazilian rural father wearing a straw hat and plaid shirt, deep gruff protective male voice"
            )
        with cd2:
            char_b_desc = st.text_input(
                "👤 Personagem B (Aparência + Voz Fixa em Inglês ou PT):",
                value="22-year-old Brazilian daughter wearing casual denim jacket, bright expressive young female voice"
            )

    elif "Modo 3" in audio_mode:
        ca1, ca2 = st.columns([2, 1])
        with ca1:
            ref_audio_file = st.file_uploader(
                "🎵 Opcional: Envie seu áudio pronto (.mp3, .wav, .m4a) para medir o tempo exato e transcrever as cenas automaticamente:",
                type=["mp3", "wav", "m4a", "ogg"]
            )
        with ca2:
            mute_flow_for_custom = st.checkbox(
                "Gerar vídeos 100% mudos no Flow",
                value=False,
                help="Se desmarcado (Recomendado), o Flow gera voz-guia apenas para a Aba 2 colocar os vídeos em ordem sozinha, e depois troca pelo seu áudio!"
            )
        if ref_audio_file is not None:
            if st.button("🎧 LER MEU ÁUDIO E MONTAR ROTEIRO SINCRONIZADO DE 8 EM 8 SEGUNDOS", use_container_width=True):
                with st.spinner("Escutando seu áudio e dividindo em blocos exatos de 8 segundos..."):
                    ffmpeg_exe = get_ffmpeg()
                    tmp_aud = os.path.join(tempfile.mkdtemp(), ref_audio_file.name)
                    with open(tmp_aud, "wb") as fa:
                        fa.write(ref_audio_file.getbuffer())
                    transcribed_script, dur_s, n_sc = transcribe_Uploaded_Audio_Chunks(
                        tmp_aud, LANGUAGES[selected_lang]["sr_code"], ffmpeg_exe
                    )
                    st.session_state["saved_script"] = transcribed_script
                    st.success(f"✅ Áudio lido ({dur_s:.1f}s -> {n_sc} cenas de 8s)! Confira na caixa abaixo e gere os prompts.")

    st.divider()
    st.markdown("### 🤖 Passo 2: Gerar Roteiro pela IA (ou usar o transcrito acima)")
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
                with st.spinner(f"Criando roteiro de {total_scenes_calc} cenas..."):
                    script_out, err_msg = generate_ai_script(
                        video_title, total_scenes_calc, selected_lang, style_choice,
                        audio_mode, char_a_desc, char_b_desc, api_key_input
                    )
                    if err_msg:
                        st.error(err_msg)
                    else:
                        st.session_state["saved_script"] = script_out
                        st.success("✅ Roteiro pronto!")

    with cs2:
        script_for_prompts = st.text_area("Roteiro Completo (Editável):", value=st.session_state["saved_script"], height=260)

    if st.button("✨ GERAR TODOS OS PROMPTS PARA O GOOGLE FLOW", type="primary", use_container_width=True):
        if not script_for_prompts.strip():
            st.warning("Gere ou cole um roteiro primeiro.")
        else:
            st.session_state["saved_script"] = script_for_prompts
            scenes = extract_scenes_for_prompts(script_for_prompts, selected_lang)
            visual_anchor = custom_style if style_choice == "Personalizado (Definir abaixo)" else STYLE_PRESETS[style_choice]
            lang_en_name = LANGUAGES[selected_lang]["name_en"]

            st.success(f"✅ {len(scenes)} Prompts gerados! Copie abaixo ou baixe o arquivo .TXT.")
            all_prompts_text = []

            for idx, sc in enumerate(scenes, 1):
                if "Modo 2" in audio_mode:
                    active_char = "Character A" if sc["speaker"] == "A" else ("Character B" if sc["speaker"] == "B" else "Character A")
                    silent_char = "Character B" if active_char == "Character A" else "Character A"
                    p_box = (
                        f"[VISUAL & CHARACTER LOCK: {visual_anchor} "
                        f"Character A MUST always be: {char_a_desc}. Character B MUST always be: {char_b_desc}. "
                        f"Single continuous 8-second shot, zero cuts, zero text on screen.]\n"
                        f"SCENE ACTION: {sc['visual']}. ONLY {active_char} moves their mouth with natural realistic lip-sync while {silent_char} keeps mouth closed listening.\n"
                        f"[DIALOGUE VOICEPRINT LOCK: Keep exact same vocal timbre for {active_char} across the entire video, native {lang_en_name}, zero background music.] "
                        f"{active_char} speaks in {lang_en_name}: \"{sc['spoken']}\""
                    )
                elif "Modo 3" in audio_mode and mute_flow_for_custom:
                    p_box = (
                        f"[VISUAL STYLE & CAMERA LOCK: {visual_anchor} "
                        f"CRITICAL RULE: Single continuous 8-second shot, zero cuts. All characters keep mouths closed in silence. Zero text on screen.]\n"
                        f"SCENE ACTION: {sc['visual']}.\n"
                        f"[AUDIO LOCK: Completely silent ambient track, zero speech, zero narration, zero music.]"
                    )
                else:
                    voice_anchor = get_strict_voice_lock(voice_choice, selected_lang, custom_voice_timbre)
                    p_box = (
                        f"[VISUAL STYLE & CAMERA LOCK: {visual_anchor} "
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

                c_list = os.path.join(ordered_dir, 'lista_uniao.txt')
                with open(c_list, 'w', encoding='utf-8') as cf:
                    for s_num, item in enumerate(results, 1):
                        n_path = os.path.join(ordered_dir, f"Cena_{s_num:03d}.mp4")
                        shutil.copy2(item['path'], n_path)
                        cf.write(f"file '{n_path.replace(chr(92), '/')}'\n")

                joined_mp4 = os.path.join(work_dir, "VIDEO_UNIDO_BASE.mp4")
                p_bar.progress(0.9, text="Unindo cenas de vídeo...")
                res = subprocess.run([ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', c_list, '-c', 'copy', joined_mp4], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode != 0 or not os.path.exists(joined_mp4):
                    subprocess.run([ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', c_list, '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', joined_mp4], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                out_mp4 = joined_mp4

                # Se o utilizador enviou o próprio áudio, substitui a faixa de áudio inteira do vídeo final!
                if master_custom_audio is not None:
                    p_bar.progress(0.95, text="Aplicando o seu próprio áudio no vídeo final...")
                    custom_aud_path = os.path.join(work_dir, master_custom_audio.name)
                    with open(custom_aud_path, "wb") as fa:
                        fa.write(master_custom_audio.getbuffer())
                    dubbed_mp4 = os.path.join(work_dir, "VIDEO_FINAL_COM_MEU_AUDIO.mp4")
                    cmd_mux = [
                        ffmpeg_exe, '-y',
                        '-i', joined_mp4,
                        '-i', custom_aud_path,
                        '-map', '0:v:0',
                        '-map', '1:a:0',
                        '-c:v', 'copy',
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-shortest',
                        dubbed_mp4
                    ]
                    res_mux = subprocess.run(cmd_mux, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res_mux.returncode == 0 and os.path.exists(dubbed_mp4):
                        out_mp4 = dubbed_mp4

                p_bar.progress(1.0, text="Concluído!")
                st.success(f"✅ Vídeo finalizado com sucesso! ({len(results)} cenas organizadas)")

                with open(out_mp4, "rb") as vf:
                    v_bytes = vf.read()
                st.download_button("💾 BAIXAR VÍDEO COMPLETO (.MP4)", data=v_bytes, file_name="VIDEO_FINAL_PRONTO.mp4", mime="video/mp4", type="primary", use_container_width=True)
                st.video(v_bytes)

                with st.expander("📋 Relatório da Ordem das Cenas"):
                    for i, r in enumerate(results, 1):
                        st.write(f"**Cena {i:03d}** (`{r['original_name']}`) — 🗣️ *{r['transcript']}*")
