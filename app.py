import streamlit as st
import pypdf
import re
import base64
from pathlib import Path
try:
    from googletrans import Translator
    translator = Translator()
    translator_available = True
except Exception:
    # googletrans (and its dependency httpx) may not work on newer Python versions
    # (e.g. Python 3.13) because of removed stdlib modules like `cgi`.
    # Fall back to disabling translation features while keeping the app runnable.
    Translator = None
    translator = None
    translator_available = False
import warnings
# Silence Streamlit's deprecation message about use_column_width which we already replaced
warnings.filterwarnings("ignore", message=".*use_column_width.*")
from gtts import gTTS
from io import BytesIO

# Try to import PyMuPDF (fitz) to render PDF pages as images when available.
try:
    import fitz
    fitz_available = True
except Exception:
    fitz = None
    fitz_available = False


# --- CONFIG & INTERFACE ---
st.set_page_config(page_title="Buku Ajaib Inggris", page_icon="🌈")

st.markdown("""
    <style>
    .stApp { background: #FFF9E1; } 
    .sentence-card { 
        background: white; padding: 15px; border-radius: 15px; 
        border-left: 10px solid #FF4B4B; margin-bottom: 10px; 
        font-size: 20px; font-weight: bold; color: #333;
    }
    .stButton>button { border-radius: 25px; height: 3em; font-weight: bold; }
    .star-counter { font-size: 24px; text-align: center; color: #E64A19; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# Session state defaults
if 'stars' not in st.session_state: st.session_state.stars = 0
if 'page' not in st.session_state: st.session_state.page = 0
# Track which sentences have been played per page (map page_index -> list of sentence indices)
if 'played_sentences' not in st.session_state: st.session_state.played_sentences = {}
# Keep list of pages already completed so we congratulate only once per page
if 'completed_pages' not in st.session_state: st.session_state.completed_pages = []
# Simple usage counter (rate limiting) per session
if 'usage_count' not in st.session_state: st.session_state.usage_count = 0
# Terms and simple invite-code authentication
if 'accepted_terms' not in st.session_state: st.session_state.accepted_terms = False
if 'authenticated' not in st.session_state: st.session_state.authenticated = False

# Compatibility helper for rerunning the script across Streamlit versions
def safe_rerun():
    """Try to rerun the Streamlit script. If the runtime doesn't expose the
    usual rerun helpers, fall back to st.stop() which ends execution and
    waits for the next user interaction.
    """
    try:
        if hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
        elif hasattr(st, "rerun"):
            st.rerun()
        else:
            st.stop()
    except Exception:
        # Best-effort fallback: stop execution so UI doesn't continue in a
        # partially-updated state.
        st.stop()

# --- NOTE ---
# The access-code UI is shown after the user accepts Terms of Use (below).

# --- TERMS OF USE ---
if not st.session_state.accepted_terms:
    st.title("🌈 Buku Ajaib Sahabat Pintar")
    st.markdown(f'<p class="star-counter">⭐ Bintang Saya: {st.session_state.stars}</p>', unsafe_allow_html=True)
    st.warning("⚠️ Aplikasi ini hanya untuk penggunaan pendidikan anak-anak. Penggunaan komersial atau penyalahgunaan dilarang.")
    if st.button("Saya Setuju"):
        st.session_state.accepted_terms = True
        safe_rerun()
    st.stop()

# --- SIMPLE AUTHENTICATION (invite code) shown AFTER Terms acceptance ---
if not st.session_state.authenticated:
    st.markdown("### 🔒 Akses Aman")
    st.info("Masukkan kode akses yang diberikan oleh guru atau organisasi untuk melanjutkan.")
    code = st.text_input("Masukkan Kode Akses (dari guru/organisasi):", type="password", key="access_code")
    if st.button("Masuk"):
        if code == "SahabatPintar2026":
            st.session_state.authenticated = True
            safe_rerun()
        else:
            st.error("Kode tidak valid. Hubungi guru/organisasi untuk mendapatkan kode akses.")
    st.stop()

st.title("🌈 Buku Ajaib Sahabat Pintar")
st.markdown(f'<p class="star-counter">⭐ Bintang Saya: {st.session_state.stars}</p>', unsafe_allow_html=True)

if not translator_available:
    st.warning("Terjemahan dinonaktifkan: modul `googletrans` tidak tersedia on this Python runtime.\n" \
               "To enable translation, use Python 3.11 or install a compatible translation library.")

# --- PERSISTENT TOP CONTROLS (mobile-friendly) ---
# Anchor for voice controls so the floating button can jump to it
st.markdown("<div id='voice-controls'></div>", unsafe_allow_html=True)
st.markdown("### 🎡 Pengaturan Suara")
col_voice, col_speed = st.columns([3, 2])
with col_voice:
    character = st.selectbox("Pilih Teman Suara:",
                             ["Guru (Normal) 👩‍🏫", "Tupai (Squeaky) 🐿️", "Beruang (Deep) 🐻", "Robot (Echo) 🤖"],
                             key="character")
with col_speed:
    speed_val = st.select_slider("Kecepatan:", options=[0.8, 1.0, 1.2], value=1.0, key="speed_val")

# Floating quick-access button removed — voice controls are persistent on the page.

# --- MAGIC VOICE ENGINE ---
def transform_audio(audio_bytes, char_type):
    # Import pydub lazily. If pydub or its dependencies are not available on this
    # Python runtime, raise an error so caller can fallback to playing raw audio.
    try:
        from pydub import AudioSegment
    except Exception as e:
        raise RuntimeError("pydub not available: %s" % e)

    sound = AudioSegment.from_file(audio_bytes, format="mp3")
    # Squirrel: faster, Bear: slower (existing behavior)
    if "Tupai" in char_type:
        new_rate = int(sound.frame_rate * 1.3)
        sound = sound._spawn(sound.raw_data, overrides={'frame_rate': new_rate}).set_frame_rate(44100)
    elif "Beruang" in char_type:
        new_rate = int(sound.frame_rate * 0.8)
        sound = sound._spawn(sound.raw_data, overrides={'frame_rate': new_rate}).set_frame_rate(44100)
    elif "Robot" in char_type or "robot" in char_type or "Robot (Echo)" in char_type:
        # Apply a child-friendly robot effect using ring modulation (LFO).
        try:
            import numpy as np

            sample_width = sound.sample_width
            channels = sound.channels
            frame_rate = sound.frame_rate

            # Only handle 16-bit PCM reliably here; otherwise fall back
            if sample_width != 2:
                raise RuntimeError("unsupported sample width for robot effect")

            # Convert raw data to numpy array
            arr = np.frombuffer(sound.raw_data, dtype=np.int16)
            if channels == 2:
                arr = arr.reshape((-1, 2))

            # Normalize to float32 in range [-1, 1]
            arr_f = arr.astype(np.float32) / 32768.0
            n_samples = arr_f.shape[0]

            # LFO parameters tuned for child-friendly metallic timbre
            lfo_freq = 40.0  # Hz
            depth = 0.6      # modulation depth (0..1)

            t = np.arange(n_samples) / float(frame_rate)
            lfo = (1.0 - depth) + depth * np.sin(2.0 * np.pi * lfo_freq * t)

            # If stereo, broadcast LFO across channels
            if channels == 2:
                lfo = lfo.reshape((-1, 1))

            modulated = arr_f * lfo

            # Convert back to int16
            mod_i = np.clip(modulated * 32767.0, -32768, 32767).astype(np.int16)
            raw_bytes = mod_i.tobytes()

            robot_seg = AudioSegment(data=raw_bytes, sample_width=2, frame_rate=frame_rate, channels=channels)
            # Keep consistent output rate
            return robot_seg.set_frame_rate(44100)
        except Exception:
            # Graceful fallback if numpy isn't available or something fails:
            # create a simple doubled/overlapped track with slight detune to sound "robotic".
            try:
                overlay = sound._spawn(sound.raw_data, overrides={'frame_rate': int(sound.frame_rate * 0.98)}).set_frame_rate(44100) - 6
                out = sound.overlay(overlay, position=40)
                return out
            except Exception:
                return sound

    return sound


# --- CONTENT FILTERING / UTILITY HELPERS ---
# A small list of banned words (expand as needed). We use word-boundary matching.
BAD_WORDS = [
    # English
    "stupid","idiot","hate","kill","dumb","ugly","fool","jerk","trash","nonsense",
    "loser","shut up","die","worthless","moron","crazy","insane","evil","nasty","gross",
    # Indonesian
    "bodoh","tolol","goblok","jelek","buruk","benci","jahat","bangsat","brengsek","anjing",
    "babi","setan","iblis","gila","hina","malas","pembohong","penipu","penjahat","sampah"
]

_bad_pattern = re.compile(r"\b(" + r"|".join([re.escape(w) for w in BAD_WORDS]) + r")\b", flags=re.IGNORECASE)

def contains_bad_words(text: str) -> bool:
    if not text:
        return False
    return bool(_bad_pattern.search(text))

def clean_text(text: str) -> str:
    # Replace any bad-word matches with a neutral placeholder
    if not text:
        return text
    return _bad_pattern.sub("🌈", text)

# --- PDF & CONTENT ---
uploaded_file = st.file_uploader("📂 Buka Buku PDF Kamu:", type="pdf")

# If the user hasn't uploaded a PDF, try to preload a bundled sample so the app
# starts with content ready to read. The sample filename is expected to live in
# the app directory.
if not uploaded_file:
    try:
        default_pdf = Path(__file__).parent / "002-GINGER-THE-GIRAFFE-Free-Childrens-Book-By-Monkey-Pen.pdf"
        if default_pdf.exists():
            data = default_pdf.read_bytes()
            uploaded_file = BytesIO(data)
            # attach a name attribute so code that expects an uploaded file's name
            # can still inspect it if needed
            uploaded_file.name = default_pdf.name
            st.info(f"Buku contoh dimuat: {default_pdf.name}")
    except Exception as e:
        st.warning(f"Gagal memuat buku contoh: {e}")

if uploaded_file:
    reader = pypdf.PdfReader(uploaded_file)
    total_pages = len(reader.pages)
    
    # Visual PDF Page Display
    if fitz_available:
        try:
            # Render the selected page as an image for reliable in-browser preview.
            doc = fitz.open(stream=uploaded_file.getvalue(), filetype="pdf")
            page_img = doc[st.session_state.page]
            pix = page_img.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("png")
            # use_column_width is deprecated; specify a pixel width instead for now.
            st.image(img_bytes, caption=f"Page {st.session_state.page + 1}", width=700)
        except Exception:
            # Fall back to data-URI iframe if rendering fails
            base64_pdf = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
            pdf_view = f'<iframe src="data:application/pdf;base64,{base64_pdf}#page={st.session_state.page + 1}" width="100%" height="400" style="border-radius:15px; border:3px solid #FFD700;"></iframe>'
            st.markdown(pdf_view, unsafe_allow_html=True)
    else:
        # If PyMuPDF not available, use an embedded PDF iframe (may be blocked on some browsers).
        base64_pdf = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
        pdf_view = f'<iframe src="data:application/pdf;base64,{base64_pdf}#page={st.session_state.page + 1}" width="100%" height="400" style="border-radius:15px; border:3px solid #FFD700;"></iframe>'
        st.markdown(pdf_view, unsafe_allow_html=True)

    # Text Splitting Logic
    raw_text = reader.pages[st.session_state.page].extract_text() or ""
    # Block the PDF page if it contains banned/offensive words
    if contains_bad_words(raw_text):
        st.error("❌ Dokumen ini berisi konten yang tidak cocok untuk anak-anak dan tidak dapat diproses.")
        st.stop()

    sentences = re.split(r'(?<=[.!?]) +', raw_text.replace('\n', ' ')) if raw_text else []

    st.write(f"### 📖 Halaman {st.session_state.page + 1}")

    for i, line in enumerate(sentences):
        if line.strip():
            safe_line = clean_text(line)
            with st.container():
                st.markdown(f'<div class="sentence-card">{safe_line}</div>', unsafe_allow_html=True)
                if st.button(f"🔊 Baca Kalimat {i+1}", key=f"s_{i}"):
                    # Simple per-session rate limiting
                    USAGE_LIMIT = 50
                    if st.session_state.usage_count >= USAGE_LIMIT:
                        st.error("⚠️ Batas penggunaan tercapai untuk sesi ini. Silakan coba lagi nanti atau hubungi admin.")
                        st.stop()
                    # 1. English Voice (generate TTS bytes) and Indonesian audio
                    #    played automatically after English.
                    tts_en = gTTS(text=safe_line, lang='en', slow=(speed_val < 1.0))
                    fp_en = BytesIO()
                    tts_en.write_to_fp(fp_en)
                    fp_en.seek(0)

                    # 2. Get Indonesian translation (if available) and prepare TTS
                    translated = None
                    if translator_available and translator is not None:
                        try:
                            translated = translator.translate(safe_line, src='en', dest='id').text
                            st.success(f"🇮🇩 Artinya: {translated}")
                        except Exception:
                            st.info("Terjemahan saat ini gagal. Coba lagi nanti.")
                    else:
                        st.info("Terjemahan tidak tersedia pada runtime ini.")

                    fp_id = None
                    if translated:
                        try:
                            tts_id = gTTS(text=translated, lang='id', slow=(speed_val < 1.0))
                            fp_id = BytesIO()
                            tts_id.write_to_fp(fp_id)
                            fp_id.seek(0)
                        except Exception:
                            fp_id = None

                    # Try to combine audio segments (apply character transform to English)
                    # so one player plays EN then ID. If pydub isn't available, fall back
                    # to playing two audio elements sequentially.
                    try:
                        from pydub import AudioSegment
                        # Transform English audio according to character
                        try:
                            en_seg = transform_audio(fp_en, character)
                        except Exception:
                            fp_en.seek(0)
                            en_seg = AudioSegment.from_file(fp_en, format="mp3")

                        if fp_id:
                            fp_id.seek(0)
                            id_seg = AudioSegment.from_file(fp_id, format="mp3")
                            combined = en_seg + AudioSegment.silent(duration=300) + id_seg
                        else:
                            combined = en_seg

                        out_fp = BytesIO()
                        combined.export(out_fp, format="mp3")
                        out_fp.seek(0)
                        st.audio(out_fp, format="audio/mp3", autoplay=True)
                    except Exception:
                        # Fallback: play separate audio players; user click should
                        # permit autoplay in most browsers since the click initiated it.
                        try:
                            fp_en.seek(0)
                            st.audio(fp_en, format="audio/mp3", autoplay=True)
                        except Exception:
                            pass
                        if fp_id:
                            try:
                                fp_id.seek(0)
                                st.audio(fp_id, format="audio/mp3", autoplay=True)
                            except Exception:
                                pass

                    # Reward for playing this sentence and usage counting
                    st.session_state.stars += 1
                    st.session_state.usage_count += 1

                    # Mark this sentence as played for the current page
                    page_idx = st.session_state.page
                    page_key = str(page_idx)
                    played = set(st.session_state.played_sentences.get(page_key, []))
                    played.add(i)
                    st.session_state.played_sentences[page_key] = list(played)

                    # If all non-empty sentences on this page have been played, congratulate once
                    total_sentences = len([s for s in sentences if s.strip()])
                    if total_sentences > 0 and len(played) >= total_sentences and page_idx not in st.session_state.completed_pages:
                        st.session_state.completed_pages.append(page_idx)
                        # Small bonus
                        st.session_state.stars += 3
                        # Mascot + written encouragement (no audio)
                        # Left: mascot emoji avatar; Right: encouraging message in a styled box
                        mcol, tcol = st.columns([1, 6])
                        with mcol:
                            # Try to load the mascot image from assets/mascots/mascot.avif and embed
                            try:
                                mascot_path = Path(__file__).parent / "assets" / "mascots" / "mascot.avif"
                                if mascot_path.exists():
                                    b = base64.b64encode(mascot_path.read_bytes()).decode('utf-8')
                                    # Use an embedded data URI so Streamlit reliably shows the image.
                                    # Style: transparent background, rounded, fixed width.
                                    st.markdown(
                                        f'<img src="data:image/avif;base64,{b}" style="width:96px;background:transparent;border-radius:12px;display:block;margin:0 auto;">',
                                        unsafe_allow_html=True,
                                    )
                                else:
                                    st.markdown('<div style="font-size:48px; text-align:center;">🦒</div>', unsafe_allow_html=True)
                            except Exception:
                                # Fallback to emoji if anything goes wrong
                                st.markdown('<div style="font-size:48px; text-align:center;">🦒</div>', unsafe_allow_html=True)
                        with tcol:
                            st.markdown(
                                f'''<div style="background:#FFFBE6;padding:12px;border-radius:12px;border:2px solid #FFD966; font-size:18px;">
                                    <strong>🎉 Hebat!</strong> Kamu sudah mendengarkan semua kalimat di halaman {page_idx + 1}. Teruskan ya!
                                </div>''',
                                unsafe_allow_html=True
                            )
                        # celebration handled via the congratulation banner above

    # Nav
    st.write("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("⬅️ Mundur") and st.session_state.page > 0:
            st.session_state.page -= 1
            safe_rerun()
    with c2:
        if st.button("Maju ➡️") and st.session_state.page < total_pages - 1:
            st.session_state.page += 1
            safe_rerun()

# --- FOOTER / DISCLAIMER ---
st.markdown("---")
st.caption("© 2026 Buku Ajaib | For educational use only. Misuse or commercial use is prohibited.")