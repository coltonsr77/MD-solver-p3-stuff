#!/usr/bin/env python3
"""
Murder Drones Viewer — Voice + Downloader — No metadata.json
- GUI viewer for images stored in ./images/
- TTS: pyttsx3 (system default voice chosen automatically)
- Speech -> commands: speech_recognition (uses Google Web Speech by default)
- Download images via scraping (requests + BeautifulSoup) from Bing image search (best-effort)
- No metadata.json — filenames used as labels

Voice commands examples:
  - "download cyn images"
  - "download solver images"
  - "download cyn 8"
  - "next" / "previous"
  - "start slideshow" / "stop slideshow"
  - "quit"

Dependencies:
  pip install pillow pyttsx3 SpeechRecognition requests beautifulsoup4
  (plus PyAudio for microphone: pipwin install pyaudio on Windows, or use your distro's portaudio)
"""
import os
import re
import time
import glob
import queue
import threading
import requests
from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk, ImageSequence
import pyttsx3
import speech_recognition as sr

# --- config ---
IMAGES_DIR = "images"
SLIDESHOW_INTERVAL = 3000  # ms
DEFAULT_DOWNLOAD_COUNT = 6
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

# --- voice assistant (auto voice) ---
class VoiceAssistant:
    def __init__(self):
        try:
            self.engine = pyttsx3.init()
        except Exception:
            self.engine = None
        self._lock = threading.Lock()
        if self.engine:
            # use system default voice (auto)
            try:
                voices = self.engine.getProperty('voices')
                if voices:
                    # don't force index; leave default
                    pass
                self.engine.setProperty("rate", 170)
            except Exception:
                pass

    def say(self, text):
        if not self.engine:
            return
        def _s():
            with self._lock:
                try:
                    self.engine.say(text)
                    self.engine.runAndWait()
                except Exception:
                    pass
        t = threading.Thread(target=_s, daemon=True)
        t.start()

# --- image item wrapper ---
class ImageItem:
    def __init__(self, path):
        self.path = path
        self._frames = []
        self._is_animated = False
        self._load()

    def _load(self):
        try:
            img = Image.open(self.path)
            self._frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
            self._is_animated = len(self._frames) > 1
        except Exception as e:
            print("Image load error:", e)
            self._frames = []

    def get_frames(self, maxsize):
        frames = []
        for f in self._frames:
            img = f.copy()
            img.thumbnail(maxsize, Image.LANCZOS)
            frames.append(ImageTk.PhotoImage(img))
        return frames

# --- scraping Bing image search (BeautifulSoup + fallback) ---
def bing_image_search_urls(query, max_results=10, timeout=12):
    """
    Best-effort scraper for Bing Image Search.
    Returns a list of image URLs (strings).
    """
    q = requests.utils.requote_uri(query)
    url = f"https://www.bing.com/images/search?q={q}&qft=+filterui:imagesize-large&FORM=IRFLTR"
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        text = r.text
        soup = BeautifulSoup(text, "html.parser")

        urls = []
        # 1) look for mimg or img tags with data-src or src
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src") or img.get("data-thumburl")
            if src and src.startswith("http"):
                urls.append(src)
            if len(urls) >= max_results:
                break

        # 2) attempt to find JSON blobs with "murl" fields via regex fallback
        if len(urls) < max_results:
            murl_matches = re.findall(r'"murl":"(http[^"]+)"', text)
            for m in murl_matches:
                u = m.replace('\\u0026', '&')
                if u not in urls:
                    urls.append(u)
                if len(urls) >= max_results:
                    break

        # 3) clean & dedupe
        out = []
        seen = set()
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
            if len(out) >= max_results:
                break
        return out
    except Exception as e:
        print("bing search error:", e)
        return []

def download_images(urls, folder, prefix="img"):
    """
    Download URLs into folder. Returns list of saved file paths.
    """
    os.makedirs(folder, exist_ok=True)
    saved = []
    for i, url in enumerate(urls, start=1):
        try:
            # attempt to pick extension
            path_part = url.split("?")[0]
            ext = os.path.splitext(path_part)[1]
            if not ext or len(ext) > 5:
                ext = ".jpg"
            fname = f"{prefix}_{int(time.time())}_{i}{ext}"
            filepath = os.path.join(folder, fname)
            headers = {"User-Agent": USER_AGENT}
            r = requests.get(url, headers=headers, timeout=12, stream=True)
            if r.status_code == 200:
                # simple safety: check content-type
                ctype = r.headers.get("content-type", "")
                if "image" not in ctype and r.headers.get("Content-Length","0") == "0":
                    print("Skipping non-image:", url)
                    continue
                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                saved.append(filepath)
                print("Saved", filepath)
            else:
                print("Bad status", r.status_code, url)
        except Exception as e:
            print("Download failed:", e, url)
    return saved

# --- speech recognition worker ---
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
            self.voice.say("Microphone not available. Voice commands disabled.")
            return
        # calibrate ambient noise briefly
        with self.mic as source:
            try:
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
            except Exception:
                pass
        self.voice.say("Voice commands ready.")
        while True:
            try:
                with self.mic as source:
                    audio = self.recognizer.listen(source, phrase_time_limit=6)
                text = self.recognizer.recognize_google(audio)
                text = text.lower().strip()
                print("Recognized:", text)
                self.q.put(text)
            except sr.UnknownValueError:
                # nothing understandable — continue listening
                continue
            except Exception as e:
                print("Speech error:", e)
                time.sleep(1)

# --- main GUI app ---
class ViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Murder Drones Viewer — Voice Downloader (no metadata)")
        self.root.geometry("1000x650")

        self.voice = VoiceAssistant()
        self.command_q = queue.Queue()
        self.speech_worker = SpeechWorker(self.command_q, self.voice)
        try:
            self.speech_worker.start()
        except Exception as e:
            print("Could not start speech worker:", e)

        self.images = []
        self.index = 0
        self.slideshow = False
        self.slideshow_job = None
        self.anim_job = None
        self.current_frames = []
        self.current_frame_index = 0

        self._load_images()
        self._build_ui()
        self._show_image(0)
        self.root.after(600, self._process_commands)

    def _load_images(self):
        if not os.path.isdir(IMAGES_DIR):
            os.makedirs(IMAGES_DIR, exist_ok=True)
        files = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp"):
            files.extend(glob.glob(os.path.join(IMAGES_DIR, ext)))
        files.sort()
        self.images = [ImageItem(p) for p in files]

    def _build_ui(self):
        left = tk.Frame(self.root)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = tk.Frame(self.root, width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Label(left, text="No images yet — say 'download cyn images' or click the Download buttons", anchor="center", justify="center")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        ctrl = tk.Frame(left)
        ctrl.pack(fill=tk.X, padx=8, pady=(0,8))
        tk.Button(ctrl, text="◀ Prev", command=self.prev_image).pack(side=tk.LEFT)
        tk.Button(ctrl, text="Next ▶", command=self.next_image).pack(side=tk.LEFT, padx=6)
        self.btn_slideshow = tk.Button(ctrl, text="Play ▶", command=self.toggle_slideshow)
        self.btn_slideshow.pack(side=tk.LEFT, padx=6)

        tk.Button(ctrl, text="Download Cyn", command=lambda: threading.Thread(target=self.download_and_reload, args=("Cyn murder drones", DEFAULT_DOWNLOAD_COUNT), daemon=True).start()).pack(side=tk.RIGHT, padx=4)
        tk.Button(ctrl, text="Download Solver", command=lambda: threading.Thread(target=self.download_and_reload, args=("Solver murder drones", DEFAULT_DOWNLOAD_COUNT), daemon=True).start()).pack(side=tk.RIGHT)

        tk.Label(right, text="Info", font=("Segoe UI", 12, "bold")).pack(anchor="nw", padx=8, pady=(8,0))
        self.info_name = tk.Label(right, text="", font=("Segoe UI", 11, "bold"), wraplength=280, justify="left")
        self.info_name.pack(anchor="nw", padx=8, pady=(4,0))
        self.info_desc = tk.Label(right, text="", wraplength=280, justify="left")
        self.info_desc.pack(anchor="nw", padx=8)

        tk.Label(right, text="Voice Commands", font=("Segoe UI", 10, "bold")).pack(anchor="nw", padx=8, pady=(10,2))
        tk.Label(right, text="Try: 'download cyn images', 'download solver', 'next', 'previous', 'start slideshow', 'stop slideshow', 'quit'").pack(anchor="nw", padx=8)

        self.status = tk.Label(self.root, text="", bd=1, relief=tk.SUNKEN, anchor="w")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        # clicking image opens file in a new window at native size
        self.canvas.bind("<Button-1>", lambda e: self._open_native())

    def _open_native(self):
        if not self.images:
            return
        path = self.images[self.index].path
        try:
            img = Image.open(path)
        except Exception:
            return
        w, h = img.size
        top = tk.Toplevel(self.root)
        top.title(os.path.basename(path))
        lbl = tk.Label(top)
        lbl.pack()
        photo = ImageTk.PhotoImage(img)
        lbl.img = photo
        lbl.config(image=photo)

    def _show_image(self, idx):
        if not self.images:
            self.canvas.config(text="No images found in the images/ folder.")
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
        # show filename as name/desc fallback
        name = os.path.basename(item.path)
        self.info_name.config(text=name)
        self.info_desc.config(text="")
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
        self.current_frames = []
        self.current_frame_index = 0
        self.anim_job = None

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
        """
        Background downloader: search, download, then reload images.
        """
        self.voice.say(f"Searching for {query}")
        self.status.config(text=f"Searching for '{query}'...")
        urls = bing_image_search_urls(query, max_results=count)
        if not urls:
            self.voice.say("Search returned no results.")
            self.status.config(text="No results.")
            return
        self.status.config(text=f"Downloading {len(urls)} images...")
        saved = download_images(urls, IMAGES_DIR, prefix=query.replace(" ", "_"))
        self.status.config(text=f"Downloaded {len(saved)} images.")
        if saved:
            self.voice.say(f"Downloaded {len(saved)} images for {query}. Reloading images.")
            self.root.after(200, self._reload_images)
        else:
            self.voice.say("Download completed but no files were saved.")

    def _reload_images(self):
        self._load_images()
        if self.images:
            self._show_image(0)

    def _process_commands(self):
        while not self.command_q.empty():
            cmd = self.command_q.get_nowait()
            print("CMD:", cmd)
            # parse download commands: "download <term> [n]"
            if cmd.startswith("download"):
                parts = cmd.split()
                if len(parts) >= 2:
                    # if second token is 'cyn' or 'solver', keep it
                    term = " ".join(parts[1:])
                else:
                    term = "cyn murder drones"
                count = DEFAULT_DOWNLOAD_COUNT
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                threading.Thread(target=self.download_and_reload, args=(term, count), daemon=True).start()
            elif cmd in ("next", "show next", "next image"):
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
                self.voice.say("Command not recognized: " + cmd)
        self.root.after(600, self._process_commands)

def main():
    root = tk.Tk()
    app = ViewerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
