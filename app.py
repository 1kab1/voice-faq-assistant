
import os
import uuid
import sqlite3
import re
import html
from contextlib import contextmanager
from datetime import datetime, timezone
import whisper
from flask import send_file
from tts_engine import synthesize_wav, tts_available

from flask import (
    Flask,
    request,
    render_template_string,
    jsonify
)

from werkzeug.utils import secure_filename
from answer_engine import answer_question
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def clean_text_for_speech(text):
    """Remove Markdown formatting before generating spoken audio."""
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"```[\s\S]*?```", " Code example omitted. ", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*+] |\d+[.)] )", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"[*_`~#]", "", text)
    text = text.replace("|", ", ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ==========================================
# APPLICATION CONFIGURATION
# ==========================================

app = Flask(__name__)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
DATABASE = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "conversations.db"))

ALLOWED_EXTENSIONS = {
    "wav", "mp3", "m4a", "ogg", "webm"
}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ==========================================
# CONVERSATION HISTORY (SQLite)
# ==========================================

@contextmanager
def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
        """)


def create_conversation():
    conversation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, "New conversation", now, now)
        )
    return conversation_id


def conversation_exists(conversation_id):
    if not conversation_id:
        return False
    with get_db() as db:
        return db.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone() is not None


def save_turn(conversation_id, question, answer):
    if not conversation_exists(conversation_id):
        conversation_id = create_conversation()
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        first_message = db.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = ? AND role = 'user'",
            (conversation_id,)
        ).fetchone()["count"] == 0
        db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conversation_id, question, now)
        )
        db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
            (conversation_id, answer, now)
        )
        title = question.strip().replace("\n", " ")[:48] or "New conversation"
        if first_message:
            db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id)
            )
        else:
            db.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id)
            )
    return conversation_id


def list_conversations():
    with get_db() as db:
        return db.execute(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
        ).fetchall()


def get_messages(conversation_id):
    with get_db() as db:
        return db.execute(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,)
        ).fetchall()


init_db()


# ==========================================
# LOAD WHISPER MODEL
# ==========================================

print("Loading Whisper model...")

model = whisper.load_model("tiny")

print("Whisper model loaded successfully!")


# ==========================================
# HTML INTERFACE
# ==========================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>Voice-Based FAQ Assistant</title>

<style>

* {
    box-sizing: border-box;
}

body {
    font-family: Arial, sans-serif;
    background: #f1f5f9;
    margin: 0;
    padding: 35px 15px;
    color: #1e293b;
}

.app-layout {
    max-width: 1180px;
    margin: auto;
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    gap: 22px;
    align-items: start;
}
.sidebar {
    background: white;
    border-radius: 16px;
    padding: 20px;
    box-shadow: 0 5px 25px rgba(0,0,0,0.06);
    position: sticky;
    top: 20px;
}
.sidebar h2 { font-size: 17px; margin: 0 0 14px; }
.new-chat { width: 100%; margin: 0 0 18px; }
.history-list { display: grid; gap: 7px; }
.history-item {
    display: block;
    padding: 10px 12px;
    color: #334155;
    text-decoration: none;
    border-radius: 9px;
    font-size: 14px;
    overflow-wrap: anywhere;
}
.history-item:hover, .history-item.active { background: #eff6ff; color: #1d4ed8; }
.history-empty { color: #94a3b8; font-size: 13px; line-height: 1.5; }
.history-delete { float: right; border: 0; background: transparent; color: #94a3b8; padding: 0 2px; margin: 0; font-size: 15px; }
.history-delete:hover { color: #dc2626; background: transparent; }
.container {
    background: white;
    max-width: 900px;
    margin: auto;
    padding: 35px;
    border-radius: 16px;
    box-shadow: 0 5px 25px rgba(0,0,0,0.08);
}

h1 {
    color: #1e3a8a;
    font-size: 30px;
    margin-bottom: 10px;
}

.subtitle {
    color: #64748b;
    margin-bottom: 30px;
}

.section {
    margin-top: 25px;
    padding: 25px;
    background: #f8fafc;
    border-radius: 12px;
}

h3 {
    margin-top: 0;
}

input[type="text"],
input[type="file"] {
    width: 100%;
    padding: 14px;
    margin: 12px 0;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    font-size: 15px;
}

button {
    background: #2563eb;
    color: white;
    border: none;
    padding: 13px 20px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 15px;
    margin: 6px 3px;
    transition: 0.2s;
}

button:hover {
    background: #1d4ed8;
}

button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.record {
    background: #dc2626;
}

.record:hover {
    background: #b91c1c;
}

.stop {
    background: #475569;
}

.stop:hover {
    background: #334155;
}

.speak {
    background: #059669;
}

.speak:hover {
    background: #047857;
}

.pause {
    background: #d97706;
}

.pause:hover {
    background: #b45309;
}

.resume {
    background: #0891b2;
}

.resume:hover {
    background: #0e7490;
}

.answer {
    background: #eff6ff;
    padding: 22px;
    margin-top: 22px;
    border-radius: 12px;
    text-align: left;
    line-height: 1.7;
    overflow-wrap: anywhere;
}

.answer strong {
    font-size: 17px;
}

.status {
    margin-top: 18px;
    font-weight: bold;
    color: #2563eb;
}

.error {
    color: #dc2626;
    background: #fef2f2;
    padding: 15px;
    border-radius: 8px;
    margin-top: 20px;
}

.hidden {
    display: none;
}

.footer {
    color: #94a3b8;
    font-size: 13px;
    margin-top: 30px;
}

</style>

</head>


<body>

<div class="app-layout">
<aside class="sidebar">
    <h2>💬 Conversation history</h2>
    <button class="new-chat" type="button" onclick="startNewConversation()">＋ New conversation</button>
    <div class="history-list">
        {% for item in conversations %}
        <div>
            <a class="history-item {% if item.id == active_conversation_id %}active{% endif %}"
               href="/?conversation_id={{ item.id }}">{{ item.title }}</a>
            <button class="history-delete" type="button" title="Delete conversation"
                    onclick="deleteConversation('{{ item.id }}')">×</button>
        </div>
        {% else %}
        <p class="history-empty">Your saved conversations will appear here.</p>
        {% endfor %}
    </div>
</aside>
<div class="container">

    <h1>🎤 Voice-Based FAQ Assistant</h1>

    <p class="subtitle">
        Ask questions about cloud computing and technology
        using text or your voice.
    </p>


    <!-- TEXT QUESTION -->

    <div class="section">

        <h3>⌨️ Ask a Question</h3>

        <form method="POST">

            <input type="hidden" name="action" value="text">
            <input type="hidden" name="conversation_id" value="{{ active_conversation_id }}">

            <input
                type="text"
                name="question"
                placeholder="What is Docker?"
                required
            >

            <button type="submit">
                Ask Assistant
            </button>

        </form>

    </div>


    <!-- LIVE MICROPHONE -->

    <div class="section">

        <h3>🎙️ Live Microphone Assistant</h3>

        <p>
            Click Start Recording and speak your question.
        </p>

        <button
            id="startBtn"
            class="record"
            onclick="startRecording()"
        >
            🔴 Start Recording
        </button>

        <button
            id="stopBtn"
            class="stop"
            onclick="stopRecording()"
            disabled
        >
            ⏹ Stop Recording
        </button>

        <div id="status" class="status">
            Ready to record.
        </div>

    </div>


    <!-- AUDIO UPLOAD -->

    <div class="section">

        <h3>📁 Upload Audio File</h3>

        <form
            method="POST"
            enctype="multipart/form-data"
        >

            <input type="hidden" name="action" value="audio">
            <input type="hidden" name="conversation_id" value="{{ active_conversation_id }}">

            <input
                type="file"
                name="audio"
                accept=".wav,.mp3,.m4a,.ogg,.webm"
                required
            >

            <button type="submit">
                Transcribe and Answer
            </button>

        </form>

    </div>


    {% if saved_messages %}
    <div class="section" id="savedConversation">
        <h3>🕘 This conversation</h3>
        {% for message in saved_messages %}
        <div class="answer" style="background: {% if message.role == 'user' %}#f1f5f9{% else %}#eff6ff{% endif %};">
            <strong>{% if message.role == 'user' %}You{% else %}🤖 Assistant{% endif %}</strong>
            <p id="savedResponse-{{ loop.index }}">{{ message.content }}</p>
            {% if message.role == 'assistant' %}
            <div class="speech-controls">
                <button class="speak" type="button" onclick="speakAnswer('savedResponse-{{ loop.index }}')">🔊 Speak Answer</button>
                <button class="pause" type="button" onclick="pauseSpeaking()">⏸ Pause</button>
                <button class="resume" type="button" onclick="resumeSpeaking()">▶ Resume</button>
                <button class="stop" type="button" onclick="stopSpeaking()">⏹ Stop</button>
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <!-- LIVE RESULTS -->

    <div id="liveResults" class="hidden">

        <div class="answer">

            <strong>🗣️ Recognized Speech:</strong>

            <p id="transcription"></p>

        </div>

        <div class="answer">

            <strong>🤖 Assistant:</strong>

            <p id="liveResponse"></p>

            <button
                class="speak"
                onclick="speakAnswer('liveResponse')"
            >
                🔊 Speak Answer
            </button>

            <button
                class="pause"
                onclick="pauseSpeaking()"
            >
                ⏸ Pause
            </button>

            <button
                class="resume"
                onclick="resumeSpeaking()"
            >
                ▶ Resume
            </button>

            <button
                class="stop"
                onclick="stopSpeaking()"
            >
                ⏹ Stop
            </button>

        </div>

    </div>


    <!-- AUDIO UPLOAD RESULTS -->

    {% if transcription %}

    <div class="answer">

        <strong>🗣️ Recognized Speech:</strong>

        <p>{{ transcription }}</p>

    </div>

    {% endif %}


    <!-- TEXT OR AUDIO ANSWER -->

    {% if answer %}

    <div class="answer">

        <strong>🤖 Assistant:</strong>

        <p id="serverResponse">{{ answer }}</p>

        <button
            class="speak"
            onclick="speakAnswer('serverResponse')"
        >
            🔊 Speak Answer
        </button>

        <button
            class="pause"
            onclick="pauseSpeaking()"
        >
            ⏸ Pause
        </button>

        <button
            class="resume"
            onclick="resumeSpeaking()"
        >
            ▶ Resume
        </button>

        <button
            class="stop"
            onclick="stopSpeaking()"
        >
            ⏹ Stop
        </button>

    </div>

    {% endif %}


    {% if error %}

    <div class="error">
        {{ error }}
    </div>

    {% endif %}


    <div id="speechStatus" class="status"></div>


    <div class="footer">

        Built with Python, Flask, Whisper and AI

        <br><br>

        Voice-Based FAQ Assistant

    </div>

</div>
</div>


<script>


// ==========================================
// CONVERSATION HISTORY
// ==========================================
let activeConversationId = {{ active_conversation_id|tojson }};

function startNewConversation() {
    window.location.href = "/";
}

async function deleteConversation(conversationId) {
    if (!confirm("Delete this conversation and all its messages?")) return;
    try {
        const response = await fetch("/api/conversations/" + conversationId, { method: "DELETE" });
        if (!response.ok) throw new Error("Could not delete conversation.");
        if (conversationId === activeConversationId) window.location.href = "/";
        else window.location.reload();
    } catch (error) {
        alert(error.message);
    }
}


// ==========================================
// MICROPHONE RECORDING
// ==========================================

let mediaRecorder;

let audioChunks = [];

let microphoneStream;


async function startRecording() {

    try {

        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia
        ) {

            throw new Error(
                "Microphone is not supported by this browser."
            );

        }

        microphoneStream =
            await navigator.mediaDevices.getUserMedia({
                audio: true
            });

        audioChunks = [];


        const mimeTypes = [
            "audio/webm;codecs=opus",
            "audio/webm",
            "audio/ogg;codecs=opus"
        ];

        const supportedType = mimeTypes.find(
            type => MediaRecorder.isTypeSupported(type)
        );


        mediaRecorder = supportedType
            ? new MediaRecorder(
                microphoneStream,
                { mimeType: supportedType }
              )
            : new MediaRecorder(microphoneStream);


        mediaRecorder.ondataavailable = function(event) {

            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }

        };


        mediaRecorder.onstop = uploadRecording;

        mediaRecorder.start();


        document.getElementById("startBtn").disabled = true;

        document.getElementById("stopBtn").disabled = false;

        document.getElementById("status").innerText =
            "🔴 Recording... Speak your question!";


    } catch (error) {

        document.getElementById("status").innerText =
            "Microphone error: " + error.message;

    }

}


// ==========================================
// STOP RECORDING
// ==========================================

function stopRecording() {

    if (
        mediaRecorder &&
        mediaRecorder.state === "recording"
    ) {

        mediaRecorder.stop();

        microphoneStream.getTracks().forEach(
            track => track.stop()
        );

        document.getElementById("startBtn").disabled = false;

        document.getElementById("stopBtn").disabled = true;

        document.getElementById("status").innerText =
            "⏳ Processing your question...";

    }

}


// ==========================================
// UPLOAD RECORDING
// ==========================================

async function uploadRecording() {

    const audioBlob = new Blob(
        audioChunks,
        { type: mediaRecorder.mimeType }
    );

    const formData = new FormData();


    const extension =
        mediaRecorder.mimeType.includes("ogg")
        ? "ogg"
        : "webm";


    formData.append(
        "audio",
        audioBlob,
        "recording." + extension
    );


    try {

        formData.append("conversation_id", activeConversationId || "");
        const response = await fetch("/transcribe", {
            method: "POST",
            body: formData
        });


        const data = await response.json();


        if (!response.ok) {

            throw new Error(
                data.error || "Audio processing failed."
            );

        }


        document.getElementById("transcription").innerText =
            data.transcription;

        document.getElementById("liveResponse").innerText =
            data.answer;

        document.getElementById("liveResults").classList.remove(
            "hidden"
        );


        document.getElementById("status").innerText =
            "✅ Question answered and saved to history!";
        if (data.conversation_id) activeConversationId = data.conversation_id;
        setTimeout(() => window.location.href = "/?conversation_id=" + activeConversationId, 900);

    } catch (error) {

        document.getElementById("status").innerText =
            "❌ " + error.message;

    }

}


// ==========================================
// TEXT TO SPEECH
// ==========================================

let currentSpeech = null;
let currentAudio = null;
let currentAudioUrl = null;

function cleanupAudio() {
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    if (currentAudioUrl) { URL.revokeObjectURL(currentAudioUrl); currentAudioUrl = null; }
}
function cleanTextForSpeech(text) {
    return String(text || "")
        .replace(/```[\s\S]*?```/g, " Code example omitted. ")
        .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
        .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
        .replace(/^\s{0,3}#{1,6}\s+/gm, "")
        .replace(/^\s*(?:[-*+] |\d+[.)] )/gm, "")
        .replace(/^\s*>\s?/gm, "")
        .replace(/[*_`~#]/g, "")
        .replace(/\|/g, ", ")
        .replace(/\s+/g, " ")
        .trim();
}

function browserSpeak(text) {
    const status = document.getElementById("speechStatus");
    if (!("speechSynthesis" in window)) {
        status.innerText = "Browser speech is not supported.";
        return;
    }

    const utterance = new SpeechSynthesisUtterance(cleanTextForSpeech(text));
    utterance.lang = "en-US";
    utterance.rate = 0.9;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find(v =>
        v.lang.toLowerCase().startsWith("en") && /natural|online/i.test(v.name)
    ) || voices.find(v => v.lang.toLowerCase() === "en-us")
      || voices.find(v => v.lang.toLowerCase().startsWith("en"));
    if (preferredVoice) utterance.voice = preferredVoice;

    currentSpeech = utterance;
    utterance.onstart = () => { status.innerText = "Speaking using browser voice..."; };
    utterance.onend = () => {
        status.innerText = "Speech finished.";
        currentSpeech = null;
    };
    utterance.onerror = (event) => {
        if (event.error !== "canceled" && event.error !== "interrupted") {
            status.innerText = "Browser speech failed: " + event.error;
        }
        currentSpeech = null;
    };
    window.speechSynthesis.speak(utterance);
}

function speakAnswer(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    const text = cleanTextForSpeech(element.innerText);
    if (!text) return;
    stopSpeaking();
    browserSpeak(text);
}

function pauseSpeaking() {
    if (currentAudio) currentAudio.pause();
    else if ("speechSynthesis" in window) window.speechSynthesis.pause();
}
function resumeSpeaking() {
    if (currentAudio) currentAudio.play();
    else if ("speechSynthesis" in window) window.speechSynthesis.resume();
}
function stopSpeaking() {
    cleanupAudio();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    currentSpeech = null;
}

</script>

</body>
</html>
"""


# ==========================================
# AUDIO PROCESSING
# ==========================================

def process_audio(audio, conversation_id=""):

    filename = secure_filename(audio.filename)

    if not filename or "." not in filename:
        raise ValueError("Invalid audio filename.")

    extension = filename.rsplit(".", 1)[-1].lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported audio format.")

    filepath = os.path.join(
        UPLOAD_FOLDER,
        str(uuid.uuid4()) + "." + extension
    )

    try:

        audio.save(filepath)

        result = model.transcribe(
            filepath,
            language="en",
            fp16=False
        )

        transcription = result["text"].strip()

        if not transcription:
            raise ValueError("No speech detected.")

        answer = answer_question(transcription, get_messages(conversation_id) if conversation_exists(conversation_id) else [])

        return transcription, answer

    finally:

        if os.path.exists(filepath):
            os.remove(filepath)


# ==========================================
# HOME ROUTE
# ==========================================

@app.route("/", methods=["GET", "POST"])
def home():
    answer = ""
    transcription = ""
    error = ""
    conversation_id = request.values.get("conversation_id", "").strip()
    if not conversation_exists(conversation_id):
        conversation_id = ""

    if request.method == "POST":
        conversation_id = request.form.get("conversation_id", "").strip()
        if not conversation_exists(conversation_id):
            conversation_id = create_conversation()
        action = request.form.get("action")

        if action == "text":
            question = request.form.get("question", "").strip()
            if question:
                answer = answer_question(question, get_messages(conversation_id))
                conversation_id = save_turn(conversation_id, question, answer)
                answer = ""
            else:
                error = "Please enter a question."

        elif action == "audio":
            audio = request.files.get("audio")
            if not audio or not audio.filename:
                error = "Please select an audio file."
            else:
                try:
                    transcription, answer = process_audio(audio, conversation_id)
                    conversation_id = save_turn(conversation_id, transcription, answer)
                    answer = ""
                    transcription = ""
                except Exception as e:
                    error = str(e)

    saved_messages = get_messages(conversation_id) if conversation_id else []
    return render_template_string(
        HTML,
        answer=answer,
        transcription=transcription,
        error=error,
        conversations=list_conversations(),
        active_conversation_id=conversation_id,
        saved_messages=saved_messages
    )


@app.route("/api/conversations", methods=["GET", "POST"])
def conversations_api():
    if request.method == "POST":
        return jsonify({"conversation_id": create_conversation()}), 201
    return jsonify([dict(row) for row in list_conversations()])


@app.route("/api/conversations/<conversation_id>", methods=["GET", "DELETE"])
def conversation_api(conversation_id):
    if not conversation_exists(conversation_id):
        return jsonify({"error": "Conversation not found."}), 404
    if request.method == "DELETE":
        with get_db() as db:
            db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return jsonify({"deleted": True})
    return jsonify({
        "conversation_id": conversation_id,
        "messages": [dict(row) for row in get_messages(conversation_id)]
    })


# ==========================================
# LIVE MICROPHONE API
# ==========================================

@app.route("/transcribe", methods=["POST"])
def transcribe():

    audio = request.files.get("audio")

    if not audio or not audio.filename:

        return jsonify({
            "error": "No audio recording received."
        }), 400

    try:

        conversation_id = request.form.get("conversation_id", "").strip()
        transcription, answer = process_audio(audio, conversation_id)
        conversation_id = save_turn(conversation_id, transcription, answer)

        return jsonify({
            "transcription": transcription,
            "answer": answer,
            "conversation_id": conversation_id
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 400


# ==========================================
# FILE SIZE ERROR
# ==========================================

@app.get("/health")
def health():
    return jsonify({"status": "ok", "whisper_loaded": model is not None, "tts_available": tts_available()})

@app.post("/api/tts")
def text_to_speech():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Text is required."}), 400
    if len(text) > 1200:
        return jsonify({"error": "Maximum speech length is 1200 characters."}), 400
    text = clean_text_for_speech(text)
    try:
        audio = synthesize_wav(text)
        return send_file(audio, mimetype="audio/wav", as_attachment=False, download_name="answer.wav")
    except Exception:
        app.logger.exception("Server TTS failed")
        return jsonify({"error": "Server speech unavailable. Try browser voice."}), 503


@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "error": "Audio file is too large. Maximum size is 20MB."
    }), 413


# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == "__main__":

    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        use_reloader=False
    )
