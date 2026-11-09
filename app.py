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

def generate_ai_script(title, minutes, lang_label, style_choice):
    num_scenes = max(4, int((minutes * 60) // 8))
    lang_info = LANGUAGES[lang_label]

    system_prompt = (
        f"You are an expert documentary and viral video scriptwriter. "
        f"Generate a complete video script about '{title}' with EXACTLY {num_scenes} scenes (each scene is 8 seconds long, totaling {minutes} minute(s)).\n"
        f"CRITICAL RULES:\n"
        f"1. Follow this exact format for every scene without skipping numbers:\n"
        f"[00:00 - 00:08]\n"
        f"[CENA: Detailed visual description in English showing the scene action, characters with mouths closed in silence]\n"
        f"LOCUÇÃO: Engaging narration written in {lang_info['name_en']} with 15 to 18 words maximum so it fits cleanly inside 8 seconds.\n\n"
        f"2. The LOCUÇÃO must be written 100% in {lang_info['name_en']}.\n"
        f"3. Every LOCUÇÃO line must have between 14 and 18 words (never exceed 20 words per scene).\n"
        f"4. The very last scene (Scene {num_scenes}) must be a warm call-to-action asking the viewer to comment below.\n"
        f"5. Output ONLY the script blocks, with a blank line between each scene."
    )

    try:
        resp = requests.post(
            "https://text.pollinations.ai/",
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Title: {title} | Duration: {minutes} min ({num_scenes} scenes of 8s) | Language: {lang_info['name_en']} | Visual Style: {style_choice}"}
                ],
                "model": "openai",
                "seed": 42
            },
            timeout=90
        )
        if resp.status_code == 200 and len(resp.text.strip()) > 50:
            return resp.text.strip()
    except Exception:
        pass

    try:
        encoded = urllib.parse.quote(f"{system_prompt}\nTitle: {title}")
        resp2 = requests.get(f"https://text.pollinations.ai/{encoded}", timeout=90)
        if resp2.status_code == 200 and len(resp2.text.strip()) > 50:
            return resp2.text.strip()
    except Exception as e:
        return f"Erro ao contatar servidor de IA: {e}"

    return "Não foi possível gerar o roteiro automaticamente neste momento. Tente novamente em alguns segundos."

def extract_scenes_for_prompts(raw_script):
    blocks = re.split(r'\n\s*\n', raw_script.strip())
    scenes = []
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        visual = ""
        spoken = ""
        for line in lines:
            m_cena = re.search(r'\[?(?:CENA|SCENE)\s*:\s*(.+?)\]?$', line, re.IGNORECASE)
            m_loc = re.search(r'(?:LOCU[ÇC][ÃA]O|LOCUCION|NARRATION|Narrador|Fala)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
            if m_cena:
                visual = m_cena.group(1).strip()
            elif m_loc:
                spoken = m_loc.group(1).strip()
            elif not re.match(r'^\[\d+:\d+', line):
                if not spoken:
                    spoken = line
        if spoken or visual:
            if not visual:
                visual = "Detailed cinematic scenery matching the narration, characters with mouths closed in silence"
            scenes.append({"visual": visual, "spoken": spoken})
    return scenes

def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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

def transcribe_video_audio(video_path, recognizer, temp_wav, sr_lang_code):
    attempts = [
        ('0.0', '8.0'),
        ('0.8', '7.0'),
        ('1.5', '6.0'),
        ('0.0', '4.5')
    ]
    for start_sec, dur_sec in attempts:
        try:
            cmd = [
                FFMPEG_EXE, '-y', '-ss', start_sec, '-i', video_path,
                '-t', dur_sec, '-vn', '-acodec', 'pcm_s16le',
                '-ar', '16000', '-ac', '1', temp_wav
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            with sr.AudioFile(temp_wav) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language=sr_lang_code)
            if text and len(text.strip()) >= 4:
                return text
        except Exception:
            continue
    return ""

def find_position_in_script(transcript, filename, full_spoken_norm, full_raw_norm, lang_label):
    t_norm = normalize_text(transcript)
    end_kw = LANGUAGES[lang_label]["end_keywords"]

    if any(kw in t_norm for kw in end_kw):
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

        best_pos = 0
        best_score = -1
        window_size = max(len(t_norm), 25)

        for pos in range(0, max(1, script_len - 8), 3):
            segment = full_spoken_norm[pos:min(script_len, pos + window_size + 20)]
            score = (fuzz.partial_ratio(t_norm, segment) * 0.65) + (fuzz.token_set_ratio(t_norm, segment) * 0.35)
            if score > best_score:
                best_score = score
                best_pos = pos

        if best_score >= 52:
            return best_pos, best_score

    return 999999, 0

st.title("🎬 Estúdio Completo Google Flow — Roteiro IA, Multi-Idiomas & Montagem")

selected_lang = st.selectbox(
    "🌍 Idioma do Vídeo (Roteiro, Locução no Google Flow e Reconhecimento de Voz):",
    list(LANGUAGES.keys())
)

tab1, tab2 = st.tabs([
    "📝 1. Criador de Roteiro IA & Gerador de Prompts",
    "🎞️ 2. Organizador e Juntador de Vídeos (Por Voz)"
])

with tab1:
    st.markdown("### 🤖 Opção A: Gerar Roteiro Completo Pelo Título (Automático)")
    col_t1, col_t2, col_t3 = st.columns([3, 1, 1])

    with col_t1:
        video_title = st.text_input(
            "Digite o Título ou Tema do Vídeo:",
            placeholder="Ex: 5 Cidades Mais Baratas e Seguras de Minas Gerais para Viver Bem"
        )
    with col_t2:
        duration_min = st.number_input(
            "Duração (Minutos):",
            min_value=1,
            max_value=15,
            value=1,
            step=1
        )
    with col_t3:
        total_scenes_calc = int((duration_min * 60) // 8)
        st.metric("Total de Cenas (8s)", f"{total_scenes_calc} cenas")

    if st.button("🪄 CRIAR ROTEIRO COMPLETO AUTOMATICAMENTE", use_container_width=True):
        if not video_title.strip():
            st.warning("Digite um título ou tema para o vídeo primeiro.")
        else:
            with st.spinner(f"Escrevendo roteiro de {duration_min} min ({total_scenes_calc} cenas) em {selected_lang}..."):
                generated = generate_ai_script(video_title, duration_min, selected_lang, "Documentário")
                st.session_state["saved_script"] = generated
                st.success("✅ Roteiro criado com sucesso! Confira abaixo e clique em 'Gerar Todos os Prompts'.")

    st.divider()
    st.markdown("### 🎙️ Opção B: Configurar Voz, Estilo e Gerar Prompts das Cenas")

    c1, c2 = st.columns([1, 1])

    with c1:
        voice_choice = st.radio(
            "Gênero da Voz do Narrador (Trava a mesma voz do início ao fim):",
            ["🎙️ Voz Masculina Fixa (Locutor Documentário)", "🎙️ Voz Feminina Fixa (Locutora Documentário)"]
        )
        style_choice = st.selectbox(
            "Estilo Visual e Personagem Fixo:",
            list(STYLE_PRESETS.keys())
        )
        custom_style = ""
        if style_choice == "Personalizado (Definir abaixo)":
            custom_style = st.text_input(
                "Descreva o estilo visual ou personagem fixo:",
                placeholder="Ex: Homem mineiro de 35 anos, camisa xadrez, realista 4K, boca fechada..."
            )

    with c2:
        script_for_prompts = st.text_area(
            "Roteiro Completo (Gerado acima ou colado manualmente):",
            value=st.session_state["saved_script"],
            height=260,
            placeholder="[00:00 - 00:08]\n[CENA: ...]\nLOCUÇÃO: ..."
        )

    if st.button("✨ GERAR TODOS OS PROMPTS COM TRAVA DE VOZ E IDIOMA", type="primary", use_container_width=True):
        if not script_for_prompts.strip():
            st.warning("Gere um roteiro pelo título acima ou cole o seu roteiro na caixa de texto.")
        else:
            st.session_state["saved_script"] = script_for_prompts
            scenes = extract_scenes_for_prompts(script_for_prompts)
            visual_anchor = custom_style if style_choice == "Personalizado (Definir abaixo)" else STYLE_PRESETS[style_choice]
            voice_anchor = get_voice_lock(voice_choice, selected_lang)
            lang_en_name = LANGUAGES[selected_lang]["name_en"]

            st.success(f"✅ {len(scenes)} Cenas prontas em {selected_lang}! (O roteiro já está salvo na Aba 2).")

            all_prompts_text = []
            for idx, sc in enumerate(scenes, 1):
                prompt_box = (
                    f"[VISUAL STYLE & CHARACTER LOCK: {visual_anchor} "
                    f"CRITICAL RULE: All characters on screen MUST keep their mouths closed and silent (strictly no lip-sync, no talking on camera). "
                    f"Zero text, zero letters, zero signs on screen.]\n"
                    f"SCENE ACTION: {sc['visual']}.\n"
                    f"{voice_anchor} Narrator says in {lang_en_name}: \"{sc['spoken']}\""
                )
                all_prompts_text.append(f"=== CENA {idx:03d} ===\n{prompt_box}\n")
                with st.expander(f"🎬 Cena {idx:03d} — \"{sc['spoken'][:65]}...\"", expanded=(idx <= 3)):
                    st.code(prompt_box, language="text")

            st.download_button(
                "📥 Baixar Todos os Prompts (.TXT)",
                data="\n".join(all_prompts_text),
                file_name="Prompts_Google_Flow.txt",
                mime="text/plain",
                use_container_width=True
            )

with tab2:
    st.subheader(f"Organizador e Juntador Automático de Vídeos ({selected_lang})")
    col1, col2 = st.columns([1, 1])

    with col1:
        roteiro_input = st.text_area(
            "📜 1. Roteiro Completo do Vídeo:",
            value=st.session_state["saved_script"],
            height=300,
            placeholder="O roteiro gerado na Aba 1 aparece aqui automaticamente..."
        )

    with col2:
        uploaded_files = st.file_uploader(
            "📦 2. Envie o arquivo .ZIP do Google Flow (ou selecione vários .MP4):",
            type=["zip", "mp4"],
            accept_multiple_files=True
        )

    if st.button("🚀 ESCUTAR CENAS, ORGANIZAR E JUNTAR VÍDEO", type="primary", use_container_width=True):
        if not roteiro_input or len(roteiro_input.strip()) < 15:
            st.error("Por favor, gere ou cole o roteiro do vídeo na caixa de texto à esquerda.")
        elif not uploaded_files:
            st.error("Por favor, envie o arquivo .ZIP ou os vídeos .MP4.")
        else:
            work_dir = tempfile.mkdtemp()
            extract_dir = os.path.join(work_dir, "extraidos")
            ordered_dir = os.path.join(work_dir, "ordenados")
            os.makedirs(extract_dir, exist_ok=True)
            os.makedirs(ordered_dir, exist_ok=True)

            mp4_files = []
            for uf in uploaded_files:
                if uf.name.lower().endswith(".zip"):
                    zip_path = os.path.join(work_dir, uf.name)
                    with open(zip_path, "wb") as f:
                        f.write(uf.getbuffer())
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        for member in z.namelist():
                            if member.lower().endswith('.mp4') and not member.startswith('__MACOSX'):
                                filename = os.path.basename(member)
                                if filename:
                                    target_path = os.path.join(extract_dir, filename)
                                    with z.open(member) as source, open(target_path, 'wb') as target:
                                        shutil.copyfileobj(source, target)
                                    mp4_files.append(target_path)
                elif uf.name.lower().endswith(".mp4"):
                    target_path = os.path.join(extract_dir, uf.name)
                    with open(target_path, "wb") as f:
                        f.write(uf.getbuffer())
                    mp4_files.append(target_path)

            if not mp4_files:
                st.error("Nenhum vídeo .MP4 foi encontrado dentro do arquivo enviado.")
            else:
                full_spoken_norm, full_raw_norm = parse_script_text(roteiro_input)
                recognizer = sr.Recognizer()
                temp_wav = os.path.join(work_dir, "_temp.wav")
                sr_code = LANGUAGES[selected_lang]["sr_code"]
                results = []

                progress_bar = st.progress(0, text=f"Iniciando reconhecimento de voz em {selected_lang}...")

                total = len(mp4_files)
                for idx, video_path in enumerate(mp4_files, 1):
                    fname = os.path.basename(video_path)
                    transcript = transcribe_video_audio(video_path, recognizer, temp_wav, sr_code)
                    pos, score = find_position_in_script(transcript, fname, full_spoken_norm, full_raw_norm, selected_lang)
                    results.append({
                        'path': video_path,
                        'original_name': fname,
                        'transcript': transcript,
                        'position': pos,
                        'score': score
                    })
                    progress_bar.progress(idx / total, text=f"Escutando cena {idx}/{total}: '{transcript[:50]}...'")

                results.sort(key=lambda x: (x['position'], x['original_name']))

                concat_list_path = os.path.join(ordered_dir, 'lista_uniao.txt')
                with open(concat_list_path, 'w', encoding='utf-8') as cf:
                    for scene_num, item in enumerate(results, 1):
                        new_name = f"Cena_{scene_num:03d}.mp4"
                        new_path = os.path.join(ordered_dir, new_name)
                        shutil.copy2(item['path'], new_path)
                        safe_path = new_path.replace('\\', '/')
                        cf.write(f"file '{safe_path}'\n")

                output_master = os.path.join(work_dir, "VIDEO_FINAL_COMPLETO_EM_ORDEM.mp4")
                progress_bar.progress(1.0, text="Unindo todas as cenas no vídeo final...")

                cmd_concat = [
                    FFMPEG_EXE, '-y', '-f', 'concat', '-safe', '0',
                    '-i', concat_list_path, '-c', 'copy', output_master
                ]
                res = subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                if res.returncode != 0 or not os.path.exists(output_master):
                    cmd_concat_reencode = [
                        FFMPEG_EXE, '-y', '-f', 'concat', '-safe', '0',
                        '-i', concat_list_path, '-c:v', 'libx264', '-preset', 'ultrafast',
                        '-c:a', 'aac', '-b:a', '192k', output_master
                    ]
                    subprocess.run(cmd_concat_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                st.success(f"✅ Vídeo unido com sucesso! ({len(results)} cenas organizadas cronologicamente)")

                with open(output_master, "rb") as vf:
                    video_bytes = vf.read()

                st.download_button(
                    label="💾 BAIXAR VÍDEO COMPLETO EM ORDEM (.MP4)",
                    data=video_bytes,
                    file_name="VIDEO_FINAL_COMPLETO_EM_ORDEM.mp4",
                    mime="video/mp4",
                    type="primary",
                    use_container_width=True
                )

                st.video(video_bytes)

                with st.expander("📋 Ver Relatório da Ordem das Cenas e Falas Reconhecidas"):
                    for i, r in enumerate(results, 1):
                        fname_orig = r['original_name']
                        fala_rec = r['transcript']
                        st.write(f"**Cena {i:03d}** (`{fname_orig}`) — 🗣️ *{fala_rec}*")
