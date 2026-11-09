import os
import re
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

LANGUAGES = {
    "🇧🇷 Português (Brasil)": {
        "sr_code": "pt-BR",
        "name_en": "Brazilian Portuguese (pt-BR)",
        "end_keywords": ["grande abraco", "visitaria primeiro", "proximo video", "proximo dossie", "comente aqui", "ate a proxima", "qual dessas"]
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

def clean_markdown(txt):
    txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt.strip())
    return re.sub(r"\n?```$", "", txt).strip()

def generate_ai_script(title, minutes, lang_label, style_choice, api_key=""):
    num_scenes = max(4, int((minutes * 60) // 8))
    lang_en = LANGUAGES[lang_label]["name_en"]

    char_hint = "the white stick figure with a blue cap exploring the real scenery" if "Palito" in style_choice else (
        "the 3D character with a blue cap exploring the real scenery" if "Cartoon" in style_choice else "cinematic documentary footage of the real location"
    )

    prompt_text = (
        f"You are an elite YouTube documentary scriptwriter known for high-retention storytelling.\n"
        f"Topic / Title: '{title}'\n"
        f"Total Duration: {minutes} minute(s) -> Write EXACTLY {num_scenes} scenes (8 seconds per scene).\n\n"
        f"MANDATORY CONTENT & QUALITY RULES:\n"
        f"1. REAL FACTS & SPECIFIC NAMES: Mention real places, specific beaches/cities, concrete facts, local curiosities, or real numbers. NEVER use generic filler or repetitive templates.\n"
        f"2. NARRATIVE FLOW: Scene 1 must be a magnetic curiosity hook. Middle scenes must smoothly transition across each real item/place of '{title}' with rich details. Scene {num_scenes} must be a friendly Call-to-Action asking viewers to comment which one they liked best (and visually waving goodbye).\n"
        f"3. STRICT TIMING PER SCENE: Every LOCUÇÃO must have between 14 and 19 words in {lang_en} so the narrator finishes speaking cleanly inside 8 seconds without rushing or cutting off.\n"
        f"4. DISTINCT VISUALS: Every [CENA: ...] must describe a unique, vivid visual action in English featuring {char_hint}, explicitly keeping all mouths closed in silence and zero text on screen.\n\n"
        f"EXACT OUTPUT FORMAT FOR ALL {num_scenes} SCENES (separated by one blank line, no intro/outro text):\n"
        f"[00:00 - 00:08]\n"
        f"[CENA: Specific visual action in English, characters silent with mouths closed, no text]\n"
        f"LOCUÇÃO: Natural, engaging narration in {lang_en} (14-19 words)."
    )

    clean_key = api_key.strip() if api_key else ""
    if not clean_key:
        return "", "⚠️ Cole sua chave gratuita da Groq (gsk_...) lá no canto superior direito e aperte ENTER! Pegue grátis em: https://console.groq.com/keys"

    last_error = ""

    # 1. ROTA GROQ CLOUD (Chaves começando com gsk_ - 100% Grátis e Ultra-Rápida)
    if clean_key.startswith("gsk_"):
        headers_groq = {
            "Authorization": f"Bearer {clean_key}",
            "Content-Type": "application/json"
        }
        for groq_model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            try:
                r_groq = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers_groq,
                    json={
                        "model": groq_model,
                        "messages": [
                            {"role": "system", "content": "You are an expert YouTube scriptwriter. Output only the requested formatted scenes."},
                            {"role": "user", "content": prompt_text}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 8000
                    },
                    timeout=90
                )
                if r_groq.status_code == 200:
                    out = clean_markdown(r_groq.json()["choices"][0]["message"]["content"])
                    if len(out) > 80:
                        return out, None
                else:
                    last_error = f"Groq HTTP {r_groq.status_code}: {r_groq.text[:200]}"
            except Exception as e_g:
                last_error = str(e_g)
        return "", f"❌ Erro na chave Groq: {last_error}"

    # 2. ROTA VERTEX AI EXPRESS (Para chaves começando com AQ.)
    if clean_key.startswith("AQ."):
        for v_model in ["gemini-2.5-flash", "gemini-2.0-flash"]:
            try:
                v_url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{v_model}:generateContent?key={clean_key}"
                r_v = requests.post(
                    v_url,
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"role": "user", "parts": [{"text": prompt_text}]}]},
                    timeout=90
                )
                if r_v.status_code == 200:
                    out = clean_markdown(r_v.json()["candidates"][0]["content"]["parts"][0]["text"])
                    if len(out) > 80:
                        return out, None
                else:
                    last_error = f"Vertex AQ HTTP {r_v.status_code}: {r_v.text[:180]}"
            except Exception as e_v:
                last_error = str(e_v)

    # 3. ROTA GEMINI AI STUDIO PADRÃO (Para chaves AIzaSy...)
    for model_id in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            g_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={clean_key}"
            r_gem = requests.post(
                g_url,
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt_text}]}]},
                timeout=90
            )
            if r_gem.status_code == 200:
                out = clean_markdown(r_gem.json()["candidates"][0]["content"]["parts"][0]["text"])
                if len(out) > 80:
                    return out, None
            else:
                last_error = f"HTTP {r_gem.status_code}: {r_gem.text[:180]}"
        except Exception as e_req:
            last_error = str(e_req)

    return "", (
        f"❌ O Google recusou essa chave ({last_error}). "
        f"Solução imediata e 100% grátis: crie uma chave 'gsk_...' em 15 segundos no site https://console.groq.com/keys e cole lá no topo!"
    )

def extract_scenes_for_prompts(raw_script):
    blocks = re.split(r'\n\s*\n', raw_script.strip())
    scenes = []
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        visual, spoken = "", ""
        for line in lines:
            m_cena = re.search(r'\[?(?:CENA|SCENE)\s*:\s*(.+?)\]?$', line, re.IGNORECASE)
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
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_script_text(raw):
    spoken_lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r'(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
        if m:
            spoken_lines.append(m.group(1).strip())
        elif not re.match(r'^\[\d+:\d+', line) and not re.match(r'^\[(?:CENA|SCENE):', line, re.IGNORECASE):
            cleaned = re.sub(r'\[(?:CENA|SCENE):.*?\]', '', line, flags=re.IGNORECASE).strip()
            if cleaned:
                spoken_lines.append(cleaned)
    full_spoken = ' '.join(spoken_lines) if spoken_lines else raw
    return normalize_text(full_spoken), normalize_text(raw)

def transcribe_video_audio(video_path, recognizer, temp_wav, sr_lang_code, ffmpeg_exe):
    import speech_recognition as sr
    for start_sec, dur_sec in [('0.0', '8.0'), ('0.8', '7.0'), ('1.5', '6.0'), ('0.0', '4.5')]:
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
        if best_score >= 52:
            return best_pos, best_score
    return 999999, 0

st.title("🎬 Estúdio Completo Google Flow — Roteiro IA, Multi-Idiomas & Montagem")

secret_key = ""
try:
    secret_key = st.secrets.get("API_KEY", "") or st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    secret_key = ""

col_top1, col_top2 = st.columns([2, 1])
with col_top1:
    selected_lang = st.selectbox("🌍 Idioma do Vídeo:", list(LANGUAGES.keys()))
with col_top2:
    api_key_input = st.text_input(
        "🔑 Chave IA Grátis (Groq 'gsk_...' ou Google):",
        value=secret_key,
        type="password",
        placeholder="Cole sua chave gsk_... e aperte ENTER"
    )

tab1, tab2 = st.tabs(["📝 1. Criador de Roteiro IA & Gerador de Prompts", "🎞️ 2. Organizador e Juntador de Vídeos (Por Voz)"])

with tab1:
    st.markdown("### 🤖 Opção A: Gerar Roteiro Profissional Pelo Título")
    col_t1, col_t2, col_t3 = st.columns([3, 1, 1])
    with col_t1:
        video_title = st.text_input("Digite o Título ou Tema do Vídeo:", placeholder="Ex: 3 Praias Paradisíacas do Nordeste")
    with col_t2:
        duration_min = st.number_input("Duração (Minutos):", min_value=1, max_value=15, value=1, step=1)
    with col_t3:
        total_scenes_calc = int((duration_min * 60) // 8)
        st.metric("Total de Cenas (8s)", f"{total_scenes_calc} cenas")

    c1, c2 = st.columns([1, 1])
    with c1:
        voice_choice = st.radio("Gênero da Voz do Narrador:", ["🎙️ Voz Masculina Fixa (Locutor Documentário)", "🎙️ Voz Feminina Fixa (Locutora Documentário)"])
        style_choice = st.selectbox("Estilo Visual e Personagem Fixo:", list(STYLE_PRESETS.keys()))
        custom_style = st.text_input("Descreva o estilo personalizado:") if style_choice == "Personalizado (Definir abaixo)" else ""

    if st.button("🪄 CRIAR ROTEIRO COMPLETO AUTOMATICAMENTE", use_container_width=True):
        if not video_title.strip():
            st.warning("Digite um título ou tema para o vídeo primeiro.")
        else:
            with st.spinner(f"Escrevendo roteiro real e detalhado de {duration_min} min ({total_scenes_calc} cenas) em {selected_lang}..."):
                script_out, err_msg = generate_ai_script(video_title, duration_min, selected_lang, style_choice, api_key_input)
                if err_msg:
                    st.error(err_msg)
                else:
                    st.session_state["saved_script"] = script_out
                    st.success("✅ Roteiro real gerado com sucesso!")

    with c2:
        script_for_prompts = st.text_area("Roteiro Completo (Editável):", value=st.session_state["saved_script"], height=260)

    if st.button("✨ GERAR TODOS OS PROMPTS COM TRAVA DE VOZ E IDIOMA", type="primary", use_container_width=True):
        if not script_for_prompts.strip():
            st.warning("Gere um roteiro acima ou cole na caixa de texto.")
        else:
            st.session_state["saved_script"] = script_for_prompts
            scenes = extract_scenes_for_prompts(script_for_prompts)
            visual_anchor = custom_style if style_choice == "Personalizado (Definir abaixo)" else STYLE_PRESETS[style_choice]
            voice_anchor = get_voice_lock(voice_choice, selected_lang)
            lang_en_name = LANGUAGES[selected_lang]["name_en"]
            st.success(f"✅ {len(scenes)} Cenas prontas em {selected_lang}!")
            all_prompts_text = []
            for idx, sc in enumerate(scenes, 1):
                p_box = (
                    f"[VISUAL STYLE & CHARACTER LOCK: {visual_anchor} "
                    f"CRITICAL RULE: All characters on screen MUST keep their mouths closed and silent (no lip-sync). Zero text on screen.]\n"
                    f"SCENE ACTION: {sc['visual']}.\n"
                    f"{voice_anchor} Narrator says in {lang_en_name}: \"{sc['spoken']}\""
                )
                all_prompts_text.append(f"=== CENA {idx:03d} ===\n{p_box}\n")
                with st.expander(f"🎬 Cena {idx:03d} — \"{sc['spoken'][:65]}...\"", expanded=(idx <= 3)):
                    st.code(p_box, language="text")
            st.download_button("📥 Baixar Todos os Prompts (.TXT)", data="\n".join(all_prompts_text), file_name="Prompts_Flow.txt", use_container_width=True)

with tab2:
    st.subheader(f"Organizador e Juntador Automático ({selected_lang})")
    col1, col2 = st.columns([1, 1])
    with col1:
        roteiro_input = st.text_area("📜 1. Roteiro Completo do Vídeo:", value=st.session_state["saved_script"], height=300)
    with col2:
        uploaded_files = st.file_uploader("📦 2. Envie o .ZIP do Google Flow (ou .MP4):", type=["zip", "mp4"], accept_multiple_files=True)

    if st.button("🚀 ESCUTAR CENAS, ORGANIZAR E JUNTAR VÍDEO", type="primary", use_container_width=True):
        if not roteiro_input or len(roteiro_input.strip()) < 15:
            st.error("Cole o roteiro do vídeo à esquerda.")
        elif not uploaded_files:
            st.error("Envie o ficheiro .ZIP ou .MP4.")
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
                full_spoken_norm, _ = parse_script_text(roteiro_input)
                recognizer = sr.Recognizer()
                temp_wav = os.path.join(work_dir, "_temp.wav")
                sr_code = LANGUAGES[selected_lang]["sr_code"]
                results = []
                p_bar = st.progress(0, text="Iniciando reconhecimento de voz...")
                total = len(mp4_files)
                for idx, v_path in enumerate(mp4_files, 1):
                    fn = os.path.basename(v_path)
                    tr = transcribe_video_audio(v_path, recognizer, temp_wav, sr_code, ffmpeg_exe)
                    pos, sc = find_position_in_script(tr, full_spoken_norm, selected_lang)
                    results.append({'path': v_path, 'original_name': fn, 'transcript': tr, 'position': pos})
                    p_bar.progress(idx / total, text=f"Escutando cena {idx}/{total}: '{tr[:45]}...'")

                results.sort(key=lambda x: (x['position'], x['original_name']))
                c_list = os.path.join(ordered_dir, 'lista_uniao.txt')
                with open(c_list, 'w', encoding='utf-8') as cf:
                    for s_num, item in enumerate(results, 1):
                        n_path = os.path.join(ordered_dir, f"Cena_{s_num:03d}.mp4")
                        shutil.copy2(item['path'], n_path)
                        cf.write(f"file '{n_path.replace(chr(92), '/')}'\n")

                out_mp4 = os.path.join(work_dir, "VIDEO_FINAL_COMPLETO_EM_ORDEM.mp4")
                p_bar.progress(1.0, text="Unindo cenas...")
                res = subprocess.run([ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', c_list, '-c', 'copy', out_mp4], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode != 0 or not os.path.exists(out_mp4):
                    subprocess.run([ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', c_list, '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', out_mp4], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                st.success(f"✅ Vídeo unido com sucesso! ({len(results)} cenas)")
                with open(out_mp4, "rb") as vf:
                    v_bytes = vf.read()
                st.download_button("💾 DESCARREGAR VÍDEO COMPLETO (.MP4)", data=v_bytes, file_name="VIDEO_FINAL_EM_ORDEM.mp4", mime="video/mp4", type="primary", use_container_width=True)
                st.video(v_bytes)
                with st.expander("📋 Relatório da Ordem das Cenas"):
                    for i, r in enumerate(results, 1):
                        st.write(f"**Cena {i:03d}** (`{r['original_name']}`) — 🗣️ *{r['transcript']}*")
