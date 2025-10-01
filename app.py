import streamlit as st
import openai
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from audiorecorder import audiorecorder
import io
# from datetime import date # dateを扱うためにインポート
from datetime import date, datetime, timezone, timedelta
import hashlib # importの追加

# --- 1. 初期設定 & 環境変数読み込み ---

# Streamlit Community CloudのSecrets、またはローカルの.envファイルから読み込む
# デプロイ時にはst.secretsを使用
try:
    openai.api_key = st.secrets["OPENAI_API_KEY"]
    PASS_KEY = st.secrets["PASS_KEY"]
    BREVO_SERVER = st.secrets["BREVO_SERVER"]
    BREVO_PORT = int(st.secrets["BREVO_PORT"])
    BREVO_USER = st.secrets["BREVO_USER"]
    BREVO_PASSWORD = st.secrets["BREVO_PASSWORD"]
    BREVO_SENDER = st.secrets["BREVO_SENDER"] # 送信元アドレスを登録＆指定が必要
except (KeyError, FileNotFoundError):
    # ローカル開発用のフォールバック
    from dotenv import load_dotenv
    load_dotenv()
    openai.api_key = os.getenv("OPENAI_API_KEY")
    PASS_KEY = os.getenv("PASS_KEY")
    BREVO_SERVER = os.getenv("BREVO_SERVER")
    BREVO_PORT = int(os.getenv("BREVO_PORT"))
    BREVO_USER = os.getenv("BREVO_USER")
    BREVO_PASSWORD = os.getenv("BREVO_PASSWORD")
    BREVO_SENDER = os.getenv("BREVO_SENDER") # 送信元アドレスを登録＆指定が必要

# セッションステートの初期化
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False
if "transcribed_text" not in st.session_state:
    st.session_state.transcribed_text = ""
if "summary_text" not in st.session_state:
    st.session_state.summary_text = ""

# --- 2. 機能関数 ---

# --- st.session_stateの初期化 ---
# アプリの初回起動時やリロード時に、必要なキーを初期化しておく
def initialize_session_state():
    if "transcribed_text" not in st.session_state:
        st.session_state.transcribed_text = ""
    if "summary_text" not in st.session_state:
        st.session_state.summary_text = ""
    if "last_audio_hash" not in st.session_state:      # ← 追加
        st.session_state.last_audio_hash = None        # ← 追加

# 3. 録音データのハッシュを取得するヘルパー
def get_audio_hash(audio_segment):
    """AudioSegment を WAV にエクスポートし、SHA‑256 ハッシュ文字列を返す"""
    buf = io.BytesIO()
    audio_segment.export(buf, format="wav")
    return hashlib.sha256(buf.getvalue()).hexdigest()
    
# 修正箇所: transcribe_audio 関数
def transcribe_audio(audio_segment):
    """Whisper APIを使ってAudioSegmentオブジェクトを文字起こしする"""
    try:
        # AudioSegmentをWAV形式のバイトデータに変換してメモリ上に保持
        wav_buffer = io.BytesIO()
        audio_segment.export(wav_buffer, format="wav")
        wav_buffer.seek(0)  # バッファのポインタを先頭に戻す

        # OpenAI APIに渡すためにファイル名を設定
        wav_buffer.name = "record.wav"
        
        with st.spinner("Whisperが音声を文字起こし中です..."):
            transcript = openai.audio.transcriptions.create(
                model="whisper-1",
                file=wav_buffer, # 修正：バイトデータが入ったバッファを渡す
            )
        return transcript.text
    except Exception as e:
        st.error(f"文字起こし中にエラーが発生しました: {e}")
        return ""


def summarize_text(text):
    """gpt-4.1-nanoを使ってテキストを要約する"""
    try:
        with st.spinner("GPTがテキストを要約中です..."):
            response = openai.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": "あなたはプロの編集者です。受け取ったテキストを簡潔で分かりやすい箇条書きの要約にしてください。"},
                    {"role": "user", "content": text}
                ],
            )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"要約中にエラーが発生しました: {e}")
        return ""

def send_email(to_address, subject, body, from_address):
    """BrevoのSMTPサーバーを使ってEmailを送信する"""
    try:
        msg = MIMEMultipart()
        msg['From'] = from_address
        msg['To'] = to_address
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with st.spinner("Emailを送信中です..."):
            server = smtplib.SMTP(BREVO_SERVER, BREVO_PORT)
            server.starttls()
            server.login(BREVO_USER, BREVO_PASSWORD)
            text = msg.as_string()
            # server.sendmail(from_address, to_address, text)
            server.sendmail(BREVO_SENDER, to_address, text)
            server.quit()
        st.success("Emailを正常に送信しました！")
    except Exception as e:
        st.error(f"Email送信中にエラーが発生しました: {e}")


# --- 3. 認証画面 ---

def check_password():
    """パスワード入力画面を表示し、認証を行う"""
    st.title("認証ページ")
    password = st.text_input("パスワードを入力してください", type="password")

    if st.button("ログイン"):
        if password == PASS_KEY:
            st.session_state.password_correct = True
            st.rerun()  # 画面を再描画してメインアプリを表示
        else:
            st.error("パスワードが間違っています。")

# --- 4. メインアプリケーション画面 ---

# 修正箇所: main_app 関数の中
def main_app():
    # 1. 利用期限を設定 (2025年10月10日)
    expiration_date = date(2025, 10, 10)
    
    # 2. 今日の日付を取得
    # today = date.today()
    # 2. JSTを取得して、その値から、日付だけを抜き取る
    JST = timezone(timedelta(hours=9), name='JST')
    now_jst = datetime.now(JST)
    today = now_jst.date()
    
    # 3. 今日の日付が利用期限を過ぎていないかチェック
    if today > expiration_date:
        st.error(f"このアプリケーションの利用期限（{expiration_date.strftime('%Y年%m月%d日')}）は終了しました。")
        st.info("ご利用ありがとうございました。")
        st.stop()  # ここでアプリの処理を完全に停止する
        
    st.title("🎙️ 音声文字起こし＆要約Email送信アプリ")

    # 最初に一度だけsession_stateを初期化
    initialize_session_state()
    
    # ... (Email入力部分は変更なし) ...
    st.subheader("1. Emailの送り先を入力")
    email_to = st.text_input("Emailアドレス", placeholder="your_email@example.com")


    # --- 音声録音 ---
    st.subheader("2. 音声を録音")
    st.write("下のマイクアイコンをクリックして録音を開始・停止します。")
    
    # 修正：変数名をaudio_segmentに変更
    audio_segment = audiorecorder(
        start_prompt="⏹️ 録音開始", 
        # stop_prompt="▶️ 録音停止",
        stop_prompt="🔴 録音中... (クリックで停止)",
        pause_prompt="",
    #    icon_size="2x"
    )

    # ★★★ ここからが修正の核心部分 ★★★
    if audio_segment is not None and len(audio_segment) > 0:
        # 現在の音声データのバイト列表現を取得
        current_hash = get_audio_hash(audio_segment)

        # 前回とハッシュが違う＝新しい録音が検出されたときのみ実行
        if st.session_state.last_audio_hash != current_hash:
            st.info("新しい音声を検出しました。文字起こし → 要約 → Email送信を開始します…")
            
            # ① **前回の結果をクリア**（ここで追加）
            st.session_state.transcribed_text = ""
            st.session_state.summary_text   = ""

            # ② 文字起こし
            trans_text = transcribe_audio(audio_segment)
            st.session_state.transcribed_text = trans_text

            # ③ 要約（失敗したら空文字）
            if trans_text.strip():
                summary = summarize_text(trans_text)
                st.session_state.summary_text = summary
            else:
                st.warning("文字起こしが失敗しました。")
                st.session_state.summary_text = ""

            # ④ Email送信
            if email_to and st.session_state.summary_text.strip():
                subject = "【自動送信】音声メモの要約"
                send_email(email_to, subject,
                           st.session_state.summary_text, BREVO_SENDER)
            else:
                st.warning("メールアドレスが未入力、または要約が空です。")

            # ハッシュを更新
            st.session_state.last_audio_hash = current_hash

            # UI を即座にリフレッシュ
            st.rerun()
    else:
        # 録音が終了していない／何も録音されていない場合はフラグをリセット
        st.session_state.processing_done = False

    # --- 文字起こし結果表示 ---
    st.subheader("3. 文字起こし結果")
    st.text_area("結果", value=st.session_state.transcribed_text, height=200, key="transcribed_display")

    # --- 要約・送信ボタンは削除したので、要約テキストとメール送信の表示だけに ---
    st.subheader("4. 要約結果")
    st.text_area("要約結果", value=st.session_state.summary_text, height=200, key="summary_display")
    
    # --- 5. Email送信（自動実行済みなら「完了」メッセージを表示） ---
    if st.session_state.last_audio_hash:
        st.success("録音 → 文字起こし → 要約 → Email送信が完了しました！")

# --- 5. アプリケーション実行 ---

# 認証が済んでいるかチェック
if st.session_state.password_correct:
    main_app()
else:
    check_password()