import sys
import pyttsx3

if __name__ == "__main__":
    text = sys.stdin.read(1201)
    if not text or len(text) > 1200:
        raise ValueError("Invalid text")
    engine = pyttsx3.init()
    engine.setProperty("rate", 165)
    engine.save_to_file(text, sys.argv[1])
    engine.runAndWait()
    engine.stop()
