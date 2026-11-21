"""Generate WAV speech with pyttsx3; uses a subprocess to isolate Linux engine state."""
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

def tts_available():
    try:
        import pyttsx3
        return True
    except ImportError:
        return False

def synthesize_wav(text):
    if not text or len(text) > 1200:
        raise ValueError("Invalid speech text length")
    with tempfile.TemporaryDirectory() as folder:
        wav = Path(folder) / "answer.wav"
        subprocess.run([sys.executable, str(Path(__file__).with_name("tts_worker.py")), str(wav)],
                       input=text, text=True, capture_output=True, timeout=40, check=True)
        data = wav.read_bytes()
        if not data.startswith(b"RIFF") or len(data) < 44:
            raise RuntimeError("pyttsx3 did not generate a valid WAV file")
        return io.BytesIO(data)
