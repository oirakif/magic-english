import streamlit as st
import pypdf
import requests
from googletrans import Translator
from gtts import gTTS
from io import BytesIO
import os
import fitz

# --- 1. APP CONFIG & STYLE ---
st.set_page_config(page_title="Magic English", page_icon="🌈", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #FFF9E1; } 
    .stButton>button { border-radius: 30px; background: #FF4B4B; color: white; font-size: 20px; height: 3.5em; width: 100%; font-weight: bold; border: none; }
    .star-box { background-color: #FFD700; padding: 15px; border-radius: 20px; text-align: center; font-size: 22px; font-weight: bold; border: 3px solid #FFA000; color: #5D4037; }
    .praise-msg { color: #D81B60; font-size: 28px; font-weight: bold; text-align: center; font-family: 'Comic Sans MS'; }
    </style>
    """, unsafe_allow_html=True)

# State Management
if 'stars' not in st.session_state: st.session_state.stars = 0
if 'page' not in st.session_state: st.session_state.page = 0
if 'current_page_audio' not in st.session_state: st.session_state.current_page_audio = (-1, "", 1.0)
translator = Translator()

st.title("🦄 My Magic English Buddy")

# --- 2. STAR COUNTER ---
st.markdown(f'<div class="star-box">Bintang Saya: {"⭐" * (st.session_state.stars % 5 + 1)} ({st.session_state.stars})</div>', unsafe_allow_html=True)

if st.session_state.stars > 0 and st.session_state.stars % 10 == 0:
    st.balloons()
    st.markdown('<p class="praise-msg">🎉 Wah, Hebat! Kamu dapat 10 bintang baru! 🎉</p>', unsafe_allow_html=True)

# --- 3. API KEY SETUP ---
API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not API_KEY:
    st.error("ELEVENLABS_API_KEY environment variable not set! Please set it before running the app.")
    st.stop()
VOICE_IDS = {
    "Mimi the Pixie 🧚‍♀️": "21m00Tcm4TlvDq8ikWAM",  # Rachel
    "Puff the Hamster 🐹": "29vD33N1CtxCmqQRPOHJ",   # Drew
    "Finley the Fox 🦊": "2EiwWnXFnvU5JabPnv8n",    # Clyde
    "Barney the Dino 🦖": "N2lVS1w4EtoT3dr4eOWO"     # Callum
}

# --- 4. MAIN APP LOGIC ---
uploaded_file = st.file_uploader("📂 Buka buku PDF kamu di sini:", type="pdf")

if uploaded_file and API_KEY:
    reader = pypdf.PdfReader(uploaded_file)
    text_en = reader.pages[st.session_state.page].extract_text()

    # Display PDF page image
    doc = fitz.open(stream=uploaded_file.getvalue(), filetype="pdf")
    page_img = doc[st.session_state.page]
    pix = page_img.get_pixmap()
    img_bytes = pix.tobytes("png")
    st.subheader("📖 PDF Page")
    st.image(img_bytes, caption=f"Page {st.session_state.page + 1}")

    col1, col2 = st.columns(2)
    with col1: char_choice = st.selectbox("Pilih Teman:", list(VOICE_IDS.keys()))
    with col2: speed = st.slider("🐢 Pelan - Cepat 🐇", 0.5, 1.3, 1.0, 0.1)

    st.subheader("📖 English Text")
    st.info(f"Halaman {st.session_state.page + 1}\n\n{text_en}")

    # Auto-generate audio if not done for this page
    if st.session_state.current_page_audio != (st.session_state.page, char_choice, speed):
        with st.spinner("Ssst... Temanmu sedang bersiap..."):
            # English Audio (ElevenLabs)
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_IDS[char_choice]}"
            headers = {"xi-api-key": API_KEY, "Content-Type": "application/json"}
            data = {"text": text_en, "model_id": "eleven_flash_v2", "voice_settings": {"speed": speed, "stability":0.5, "similarity_boost":0.75}}
            res_en = requests.post(url, json=data, headers=headers)
            
            # Indonesian Translation & Audio (gTTS)
            translated = translator.translate(text_en, src='en', dest='id')
            text_id = translated.text
            tts_id = gTTS(text=text_id, lang='id')
            fp_id = BytesIO()
            tts_id.write_to_fp(fp_id)

            if res_en.status_code == 200 and res_en.content:
                st.subheader("🔊 English Audio")
                st.audio(res_en.content, format="audio/mp3")
                st.subheader("🇮🇩 Terjemahan Bahasa Indonesia")
                st.success(text_id)
                st.subheader("🔊 Indonesian Audio")
                st.audio(fp_id, format="audio/mp3")
                st.session_state.stars += 1
                st.session_state.current_page_audio = (st.session_state.page, char_choice, speed)
            else:
                st.error(f"Gagal membuat audio English: {res_en.status_code} - {res_en.text if hasattr(res_en, 'text') and res_en.text else 'No response'}")
                # Still try Indonesian audio
                st.subheader("🇮🇩 Terjemahan Bahasa Indonesia")
                st.success(text_id)
                st.subheader("🔊 Indonesian Audio")
                st.audio(fp_id, format="audio/mp3")
                st.session_state.current_page_audio = (st.session_state.page, char_choice, speed)

    # Navigation
    st.write("---")
    n1, n2 = st.columns(2)
    with n1:
        if st.button("⬅️ Mundur") and st.session_state.page > 0:
            st.session_state.page -= 1
            st.rerun()
    with n2:
        if st.button("Maju ➡️") and st.session_state.page < len(reader.pages)-1:
            st.session_state.page += 1
            st.rerun()
else:
    st.warning("Silakan masukkan API Key di samping dan pilih buku PDF!")