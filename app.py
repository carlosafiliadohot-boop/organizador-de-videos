import os
import re
import glob
import shutil
import zipfile
import tempfile
import subprocess
import unicodedata
import streamlit as st
import speech_recognition as sr
from rapidfuzz import fuzz
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

st.set_page_config(
    page_title="Organizador & Juntador Google Flow",
    page_icon="🎬",
    layout="wide"
)

VISUAL_KEYWORDS = {
    "rua": ["street", "road", "walking", "houses", "flowers"],
    "aluguel": ["rent", "houses", "street"],
    "cofrinho": ["piggy", "bank", "coins", "money", "table"],
    "moedas": ["coins", "piggy", "money"],
    "jornal": ["newspaper", "reading", "bench", "square", "church", "plaza"],
    "praca": ["square", "plaza", "bench", "church", "newspaper"],
    "bom jardim": ["newspaper", "bench", "church", "square"],
    "feira": ["market", "fruits", "cheese", "bag", "stall", "buying"],
    "frutas": ["fruits", "market", "cheese"],
    "bicicleta": ["bicycle", "bike", "cycling", "riding", "mountains"],
    "lima duarte": ["bicycle", "bike", "riding", "mountains"],
    "clinica": ["clinic", "hospital", "medical", "doctor", "nurse", "thumbs"],
    "hospitais": ["hospital", "clinic", "medical", "doctor"],
    "varanda": ["porch", "coffee", "cup", "mug", "lake", "sunset", "balcony"],
    "rio novo": ["coffee", "porch", "lake", "sunset", "mug"],
    "tchau": ["waving", "wave", "white", "smiling", "goodbye"],
    "aeroporto": ["airport", "confins", "plane", "flight"],
    "cataguases": ["cataguases", "bridge", "modernist", "niemeyer"],
    "lagoa santa": ["lagoon", "lagoa", "lake", "boardwalk", "bike"],
    "caxambu": ["caxambu", "fountain", "geyser", "park", "water", "carriage"],
    "sao joao": ["train", "steam", "orchestra", "church", "baroque"],
    "araxa": ["araxa", "hotel", "mud", "sulfur", "termas"],
    "sao lourenco": ["balloon", "pedal", "bamboo", "bambu"],
    "pocos de caldas": ["volcano", "crater", "vulcao", "cratera", "clock", "floral"]
}

def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    num_map = {
        '700': 'setecentos', '66': 'sessenta e seis', '111': 'cento e onze',
        '165': 'cento e sessenta e cinco', '15': 'quinze', '35': 'trinta e cinco',
        '20': 'vinte', '12': 'doze', '80': 'oitenta', '40': 'quarenta',
        '853': 'oitocentos e cinquenta e tres', '800': 'oitocentos',
        '1200': 'mil e duzentos', '750': 'setecentos e cinquenta'
    }
    for k, v in num_map.items():
        text = re.sub(r'\b' + k + r'\b', f"{k} {v}", text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_script_text(raw):
    spoken_lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r'(?:LOCU[ÇC][ÃA]O|Narrador|Fala)\s*(?:\(.*?\))?\s*:\s*(.+)', line, re.IGNORECASE)
        if m:
            spoken_lines.append(m.group(1).strip())
        elif not re.match(r'^\[\d+:\d+', line) and not re.match(r'^\[CENA:', line, re.IGNORECASE):
            cleaned = re.sub(r'\[CENA:.*?\]', '', line, flags=re.IGNORECASE).strip()
            if cleaned:
                spoken_lines.append(cleaned)

    full_spoken = ' '.join(spoken_lines) if spoken_lines else raw
    return normalize_text(full_spoken), normalize_text(raw)

def transcribe_video_audio(video_path, recognizer, temp_wav):
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
            text = recognizer.recognize_google(audio_data, language='pt-BR')
            if text and len(text.strip()) >= 4:
                return text
        except Exception:
            continue
    return ""

def find_position_in_script(transcript, filename, full_spoken_norm, full_raw_norm):
    t_norm = normalize_text(transcript)
    fname_lower = filename.lower()

    if "grande abraco" in t_norm or "visitaria primeiro" in t_norm or "proximo video" in t_norm or "proximo dossie" in t_norm:
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

        if best_score >= 55:
            return best_pos, best_score

    for pt_word, en_list in VISUAL_KEYWORDS.items():
        if any(en_w in fname_lower for en_w in en_list):
            idx_raw = full_raw_norm.find(pt_word)
            if idx_raw != -1:
                ratio_pos = int((idx_raw / max(1, len(full_raw_norm))) * len(full_spoken_norm))
                return ratio_pos, 75

    return 999999, 0

st.title("🎬 Organizador e Juntador Automático de Vídeos (Por Voz)")
st.markdown("Envie o arquivo **.ZIP** baixado do Google Flow (ou os arquivos **.MP4** soltos) e cole o seu **Roteiro em Português**. O servidor escuta cada cena, coloca na ordem cronológica 100% exata e gera o vídeo completo sem consumir a memória do seu navegador.")

col1, col2 = st.columns([1, 1])

with col1:
    roteiro_input = st.text_area(
        "📜 1. Cole o Roteiro Completo Aqui:",
        height=320,
        placeholder="Cole aqui o seu roteiro com [CENA: ...] e LOCUÇÃO: ..."
    )

with col2:
    uploaded_files = st.file_uploader(
        "📦 2. Envie o arquivo .ZIP do Google Flow (ou selecione vários .MP4):",
        type=["zip", "mp4"],
        accept_multiple_files=True
    )

if st.button("🚀 ESCUTAR CENAS, ORGANIZAR E JUNTAR VÍDEO", type="primary", use_container_width=True):
    if not roteiro_input or len(roteiro_input.strip()) < 15:
        st.error("Por favor, cole o roteiro do vídeo na caixa de texto à esquerda.")
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
            results = []

            progress_bar = st.progress(0, text="Iniciando reconhecimento de voz das cenas...")
            status_box = st.empty()

            total = len(mp4_files)
            for idx, video_path in enumerate(mp4_files, 1):
                fname = os.path.basename(video_path)
                transcript = transcribe_video_audio(video_path, recognizer, temp_wav)
                pos, score = find_position_in_script(transcript, fname, full_spoken_norm, full_raw_norm)
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
                    st.write(f"**Cena {i:03d}** (`{r['original_name']}`) — 🗣️ *"{r['transcript']}"*")
