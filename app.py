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

if 'stars' not in st.session_state: st.session_state.stars = 0
if 'page' not in st.session_state: st.session_state.page = 0
# Track which sentences have been played per page (map page_index -> list of sentence indices)
if 'played_sentences' not in st.session_state: st.session_state.played_sentences = {}
# Keep list of pages already completed so we congratulate only once per page
if 'completed_pages' not in st.session_state: st.session_state.completed_pages = []

st.title("🌈 Buku Ajaib Sahabat Pintar")
st.markdown(f'<p class="star-counter">⭐ Bintang Saya: {st.session_state.stars}</p>', unsafe_allow_html=True)

if not translator_available:
    st.warning("Terjemahan dinonaktifkan: modul `googletrans` tidak tersedia on this Python runtime.\n" \
               "To enable translation, use Python 3.11 or install a compatible translation library.")

# --- SIDEBAR CONTROLS ---
st.sidebar.header("🎡 Pengaturan Suara")
character = st.sidebar.selectbox("Pilih Teman Suara:", 
                                ["Guru (Normal) 👩‍🏫", "Tupai (Squeaky) 🐿️", "Beruang (Deep) 🐻", "Robot (Echo) 🤖"])
speed_val = st.sidebar.select_slider("Kecepatan Membaca:", options=[0.8, 1.0, 1.2], value=1.0)

# --- MAGIC VOICE ENGINE ---
def transform_audio(audio_bytes, char_type):
    # Import pydub lazily. If pydub or its dependencies are not available on this
    # Python runtime, raise an error so caller can fallback to playing raw audio.
    try:
        from pydub import AudioSegment
    except Exception as e:
        raise RuntimeError("pydub not available: %s" % e)

    sound = AudioSegment.from_file(audio_bytes, format="mp3")
    if "Tupai" in char_type:
        new_rate = int(sound.frame_rate * 1.3)
        sound = sound._spawn(sound.raw_data, overrides={'frame_rate': new_rate}).set_frame_rate(44100)
    elif "Beruang" in char_type:
        new_rate = int(sound.frame_rate * 0.8)
        sound = sound._spawn(sound.raw_data, overrides={'frame_rate': new_rate}).set_frame_rate(44100)
    return sound

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
    sentences = re.split(r'(?<=[.!?]) +', raw_text.replace('\n', ' ')) if raw_text else []

    st.write(f"### 📖 Halaman {st.session_state.page + 1}")

    for i, line in enumerate(sentences):
        if line.strip():
            with st.container():
                st.markdown(f'<div class="sentence-card">{line}</div>', unsafe_allow_html=True)
                if st.button(f"🔊 Baca Kalimat {i+1}", key=f"s_{i}"):
                    # 1. English Voice (generate TTS bytes)
                    tts_en = gTTS(text=line, lang='en', slow=(speed_val < 1.0))
                    fp_en = BytesIO()
                    tts_en.write_to_fp(fp_en)
                    fp_en.seek(0)

                    # Try applying audio transform; if anything fails, play original bytes.
                    try:
                        final_audio = transform_audio(fp_en, character)
                        out_fp = BytesIO()
                        final_audio.export(out_fp, format="mp3")
                        out_fp.seek(0)
                        st.audio(out_fp, format="audio/mp3", autoplay=True)
                    except Exception:
                        fp_en.seek(0)
                        st.audio(fp_en, format="audio/mp3", autoplay=True)
                        st.info("Efek suara tidak tersedia pada runtime ini; memutar audio asli.")

                    # 2. Translation (if available)
                    if translator_available and translator is not None:
                        try:
                            translated = translator.translate(line, src='en', dest='id').text
                            st.success(f"🇮🇩 Artinya: {translated}")
                        except Exception:
                            st.info("Terjemahan saat ini gagal. Coba lagi nanti.")
                    else:
                        st.info("Terjemahan tidak tersedia pada runtime ini.")
                    # Reward for playing this sentence
                    st.session_state.stars += 1
                    if st.session_state.stars % 10 == 0:
                        st.balloons()

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
                        st.balloons()

    # Nav
    st.write("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("⬅️ Mundur") and st.session_state.page > 0:
            st.session_state.page -= 1
            st.rerun()
    with c2:
        if st.button("Maju ➡️") and st.session_state.page < total_pages - 1:
            st.session_state.page += 1
            st.rerun()