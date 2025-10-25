#!/usr/bin/env python3
"""
Murder Drones Viewer + Voice + Downloader
- GUI viewer for images in ./images/
- TTS notifications (pyttsx3)
- Microphone commands (speech_recognition)
- Web image search + download (Bing scraping, best-effort)

Commands you can say (examples):
 - "download cyn images"
 - "download solver images"
 - "download cyn 10"        # download 10 images
 - "show next" / "next"
 - "show previous" / "previous"
 - "start slideshow" / "stop slideshow"
 - "quit" / "exit"

Dependencies:
    pip install pillow pyttsx3 SpeechRecognition requests
    pipwin install pyaudio       # on Windows (or install PyAudio by other means)
"""

import os
import re
import json
import glob
import time
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageSequence
import requests
import pyttsx3
import speech_recognition as sr

IMAGES_DIR = "images"
METADATA_FILE = "metadata.json"
SLIDESHOW_INTERVAL = 3000  # ms
DEFAULT_DOWNLOAD_COUNT = 6
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

# ---------- Utilities: speech ----------
class VoiceAssistant:
    def __init__(self):
        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", 170)
        # pick default voice (0)
        voices = self.engine.getProperty('voices')
        if voices:
            self.engine.setProperty("voice", voices[0].id)
        self._lock = threading.Lock()

    def say(self, text):
        def _s():
            with self._lock:
                self.engine.say(text)
                self.engine.runAndWait()
        t = threading.Thread(target=_s, daemon=True)
        t.start()

# ---------- Image item ----------
class ImageItem:
    def __init__(self, path, meta=None):
        self.path = path
        self.meta = meta or {}
        self._frames = []
        self._is_animated = False
        self._load()

    def _load(self):
        try:
            img = Image.open(self.path)
            self._frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
            self._is_animated = len(self._frames) > 1
        except Exception as e:
            print("Load error:", e)
            self._frames = []

    def get_frames(self, maxsize):
        frames = []
        for f in self._frames:
            img = f.copy()
            img.thumbnail(maxsize, Image.LANCZOS)
            frames.append(ImageTk.PhotoImage(img))
        return frames

# ---------- Web image search & download (best-effort Bing scraping) ----------
def bing_image_search_urls(query, max_results=10, timeout=10):
    """
    Scrape Bing image search results page for image URLs.
    Returns list of image URLs (strings). Best-effort; may miss results or break if Bing changes layout.
    """
    q = requests.utils.requote_uri(query)
    url = f"https://www.bing.com/images/search?q={q}&qft=+filterui:imagesize-large&FORM=IRFLTR"
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        text = r.text
        # Attempt to extract "murl" fields which often contain image URLs in Bing JSON blobs
        murl_matches = re.findall(r'"murl":"(http[^"]+)"', text)
        urls = []
        for m in murl_matches:
            # unescape
            u = m.replace('\\u0026', '&')
            urls.append(u)
            if len(urls) >= max_results:
                break
        # fallback: search for <img src="..." class="mimg"
        if len(urls) < max_results:
            img_matches = re.findall(r'<img[^>]+class="[^"]*mimg[^"]*"[^>]+src="([^"]+)"', text)
            for im in img_matches:
                if im.startswith("http"):
                    urls.append(im)
                    if len(urls) >= max_results:
                        break
        # final dedupe
        seen = set()
        out = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out
    except Exception as e:
        print("bing search error:", e)
        return []

def download_images(urls, folder, prefix="img"):
    """
    Download each URL into folder, returning list of saved file paths.
    """
    os.makedirs(folder, exist_ok=True)
    saved = []
    for i, url in enumerate(urls, start=1):
        try:
            ext = os.path.splitext(url.split("?")[0])[1]
            if not ext or len(ext) > 5:
                ext = ".jpg"
            fname = f"{prefix}_{int(time.time())}_{i}{ext}"
            path = os.path.join(folder, fname)
            headers = {"User-Agent": USER_AGENT}
            r = requests.get(url, headers=headers, timeout=12, stream=True)
            if r.status_code == 200 and int(r.headers.get("Content-Length", 0)) > 0 or 'image' in r.headers.get('Content-Type',''):
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1024*8):
                        f.write(chunk)
                saved.append(path)
                print("Saved", path)
            else:
                print("Skipped (bad response):", url)
        except Exception as e:
            print("Download failed:", e, url)
    return saved

# ---------- Speech recognition worker ----------
class SpeechWorker(threading.Thread):
    def __init__(self, command_queue, voice):
        super().__init__(daemon=True)
        self.q = command_queue
        self.voice = voice
        self.recognizer = sr.Recognizer()
        try:
            self.mic = sr.Microphone()
        except Exception:
            self.mic = None
            print("Microphone not available.")

    def run(self):
        if not self.mic:
            return
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        self.voice.say("Voice commands enabled. Say download cyn or download solver to fetch images.")
        while True:
            try:
                with self.mic as source:
                    audio = self.recognizer.listen(source, phrase_time_limit=5)
                text = self.recognizer.recognize_google(audio)
                text = text.lower().strip()
                print("Heard:", text)
                self.q.put(text)
            except sr.UnknownValueError:
                continue
            except Exception as e:
                print("Speech error:", e)
                time.sleep(1)

# ---------- GUI / App ----------
class ViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Murder Drones Viewer (Voice + Downloader)")
        self.root.geometry("1000x650")
        self.voice = VoiceAssistant()

        self.images = []
        self.index = 0
        self.slideshow = False
        self.slideshow_job = None
        self.anim_job = None
        self.current_frames = []
        self.current_frame_index = 0

        self.command_q = queue.Queue()
        self.speech_worker = SpeechWorker(self.command_q, self.voice)
        # start speech worker thread (it will ask to start microphone)
        try:
            self.speech_worker.start()
        except Exception as e:
            print("Could not start speech thread:", e)

        self._load_metadata()
        self._load_images()
        self._build_ui()
        self._show_image(0)

        # start command poll loop
        self.root.after(500, self._process_commands)

    def _load_metadata(self):
        self.metadata = {}
        if os.path.exists(METADATA_FILE):
            try:
                with open(METADATA_FILE, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            except Exception as e:
                print("metadata load error:", e)

    def _load_images(self):
        if not os.path.isdir(IMAGES_DIR):
            os.makedirs(IMAGES_DIR, exist_ok=True)
        files = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp"):
            files.extend(glob.glob(os.path.join(IMAGES_DIR, ext)))
        files.sort()
        self.images = [ImageItem(f, self.metadata.get(os.path.basename(f))) for f in files]

    def _build_ui(self):
        left = tk.Frame(self.root)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = tk.Frame(self.root, width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Label(left, text="No images found. Use voice: 'download cyn' or 'download solver'", anchor="center", justify="center")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        ctrl = tk.Frame(left)
        ctrl.pack(fill=tk.X, padx=8, pady=(0,8))
        tk.Button(ctrl, text="◀ Prev", command=self.prev_image).pack(side=tk.LEFT)
        tk.Button(ctrl, text="Next ▶", command=self.next_image).pack(side=tk.LEFT, padx=6)
        self.btn_slideshow = tk.Button(ctrl, text="Play ▶", command=self.toggle_slideshow)
        self.btn_slideshow.pack(side=tk.LEFT, padx=6)
        tk.Button(ctrl, text="Download Cyn", command=lambda: threading.Thread(target=self.download_and_reload, args=("Cyn murder drones",), daemon=True).start()).pack(side=tk.RIGHT, padx=4)
        tk.Button(ctrl, text="Download Solver", command=lambda: threading.Thread(target=self.download_and_reload, args=("Solver murder drones",), daemon=True).start()).pack(side=tk.RIGHT)

        tk.Label(right, text="Info", font=("Segoe UI", 12, "bold")).pack(anchor="nw", padx=8, pady=(8,0))
        self.info_name = tk.Label(right, text="", font=("Segoe UI", 11, "bold"), wraplength=280, justify="left")
        self.info_name.pack(anchor="nw", padx=8, pady=(4,0))
        self.info_desc = tk.Label(right, text="", wraplength=280, justify="left")
        self.info_desc.pack(anchor="nw", padx=8, pady=(6,8))

        tk.Label(right, text="Voice Commands", font=("Segoe UI", 10, "bold")).pack(anchor="nw", padx=8, pady=(10,2))
        tk.Label(right, text="Say: 'download cyn images' or 'download solver images'\nSay: 'next', 'previous', 'start slideshow', 'stop slideshow', 'quit'").pack(anchor="nw", padx=8)

        self.status = tk.Label(self.root, text="", bd=1, relief=tk.SUNKEN, anchor="w")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    def _show_image(self, idx):
        if not self.images:
            self.canvas.config(text="No images found in 'images/' - say 'download cyn images' or click Download Cyn.")
            self.info_name.config(text="")
            self.info_desc.config(text="")
            self.status.config(text="0 images")
            return

        self._stop_animation()
        self.index = idx % len(self.images)
        item = self.images[self.index]
        max_w = max(200, self.root.winfo_width() - 360)
        max_h = max(200, self.root.winfo_height() - 120)
        frames = item.get_frames((max_w, max_h))
        if not frames:
            self.canvas.config(text="Failed to load image.")
            return

        self.current_frames = frames
        self.current_frame_index = 0
        self.canvas.config(image=frames[0])
        self.canvas.image = frames[0]
        self.status.config(text=f"{self.index+1}/{len(self.images)} — {os.path.basename(item.path)}")

        meta = item.meta or {}
        name = meta.get("name", os.path.basename(item.path))
        desc = meta.get("desc", "No description.")
        self.info_name.config(text=name)
        self.info_desc.config(text=desc)
        # speak
        self.voice.say(f"Now showing {name}")

        if item._is_animated and len(frames) > 1:
            self._animate_gif()

    def _animate_gif(self):
        if not self.current_frames:
            return
        frame = self.current_frames[self.current_frame_index]
        self.canvas.config(image=frame)
        self.canvas.image = frame
        self.current_frame_index = (self.current_frame_index + 1) % len(self.current_frames)
        self.anim_job = self.root.after(120, self._animate_gif)

    def _stop_animation(self):
        if self.anim_job:
            try:
                self.root.after_cancel(self.anim_job)
            except Exception:
                pass
            self.anim_job = None
        self.current_frames = []
        self.current_frame_index = 0

    def next_image(self):
        if not self.images:
            return
        self._show_image(self.index + 1)

    def prev_image(self):
        if not self.images:
            return
        self._show_image(self.index - 1)

    def toggle_slideshow(self):
        if self.slideshow:
            self._stop_slideshow()
        else:
            self._start_slideshow()

    def _start_slideshow(self):
        if not self.images:
            return
        self.slideshow = True
        self.btn_slideshow.config(text="Pause ⏸")
        self._schedule_slideshow()

    def _schedule_slideshow(self):
        self.slideshow_job = self.root.after(SLIDESHOW_INTERVAL, self._slideshow_step)

    def _slideshow_step(self):
        self.next_image()
        if self.slideshow:
            self._schedule_slideshow()

    def _stop_slideshow(self):
        self.slideshow = False
        self.btn_slideshow.config(text="Play ▶")
        if self.slideshow_job:
            try:
                self.root.after_cancel(self.slideshow_job)
            except Exception:
                pass
            self.slideshow_job = None

    def download_and_reload(self, query, count=DEFAULT_DOWNLOAD_COUNT):
        """Download images for query and reload viewer (runs in a background thread)."""
        self.voice.say(f"Searching for {query} images")
        self.status.config(text=f"Searching for {query}...")
        urls = bing_image_search_urls(query, max_results=count)
        if not urls:
            self.voice.say("No results found or search failed.")
            self.status.config(text="Search failed / no results.")
            return
        self.status.config(text=f"Downloading {len(urls)} images...")
        saved = download_images(urls, IMAGES_DIR, prefix=query.replace(" ", "_"))
        self.status.config(text=f"Downloaded {len(saved)} images.")
        if saved:
            self.voice.say(f"Downloaded {len(saved)} images for {query}. Reloading viewer.")
            # reload images on main thread
            self.root.after(200, self._reload_images)
        else:
            self.voice.say("Download finished but no files were saved.")

    def _reload_images(self):
        self._load_images()
        if self.images:
            self._show_image(0)

    def _process_commands(self):
        """Check for voice commands in the queue and act on them."""
        while not self.command_q.empty():
            cmd = self.command_q.get_nowait()
            print("Command received:", cmd)
            if cmd.startswith("download"):
                # parse: download <term> [n]
                parts = cmd.split()
                if len(parts) >= 2:
                    # assemble search term
                    if parts[1] in ("cyn", "solver", "uzi", "n", "absolute", "solver"):
                        term = " ".join(parts[1:])
                    else:
                        term = " ".join(parts[1:])
                else:
                    term = "cyn murder drones"
                # if last token numeric, treat as count
                count = DEFAULT_DOWNLOAD_COUNT
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                # start download in background
                threading.Thread(target=self.download_and_reload, args=(term, count), daemon=True).start()
            elif cmd in ("next", "show next", "next image", "show next image"):
                self.next_image()
            elif cmd in ("previous", "prev", "show previous"):
                self.prev_image()
            elif cmd in ("start slideshow", "play slideshow", "start"):
                self._start_slideshow()
            elif cmd in ("stop slideshow", "stop"):
                self._stop_slideshow()
            elif cmd in ("quit", "exit", "close"):
                self.voice.say("Goodbye")
                self.root.quit()
            else:
                # unknown - speak back
                self.voice.say("Command not recognized: " + cmd)
        # schedule next poll
        self.root.after(600, self._process_commands)

def main():
    root = tk.Tk()
    app = ViewerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
