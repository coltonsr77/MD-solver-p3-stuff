#!/usr/bin/env python3
"""
Murder Drones Viewer
- Put your images in a folder named `images/` (or change IMAGES_DIR).
- Provide optional metadata in `metadata.json` with keys equal to filenames.
  Example metadata.json:
  {
    "worker1.png": {"name": "Worker 1", "desc": "Short bio or quote."},
    "droneA.gif": {"name": "Drone A", "desc": "Villainous and dramatic."}
  }

Dependencies:
    pip install pillow

Run:
    python murder_drones_viewer.py
"""

import os
import json
import glob
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageSequence

# CONFIG
IMAGES_DIR = "images"
METADATA_FILE = "metadata.json"
SLIDESHOW_INTERVAL = 3000  # ms

class ImageItem:
    def __init__(self, path, meta=None):
        self.path = path
        self.meta = meta or {}
        self._pil = None
        self._frames = None
        self._is_animated = False
        self._load()

    def _load(self):
        try:
            img = Image.open(self.path)
            self._pil = img.copy()
            # check for GIF animation
            try:
                self._frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
                self._is_animated = len(self._frames) > 1
            except Exception:
                self._frames = [self._pil]
                self._is_animated = False
        except Exception as e:
            print(f"Failed to load {self.path}: {e}")
            self._pil = None
            self._frames = []

    def get_frames(self, maxsize):
        """
        Return list of PhotoImage frames resized to maxsize preserving aspect ratio.
        maxsize: (w,h)
        """
        frames = []
        for f in self._frames:
            img = f.copy()
            img.thumbnail(maxsize, Image.LANCZOS)
            frames.append(ImageTk.PhotoImage(img))
        return frames

class ViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Murder Drones Viewer")
        self.root.geometry("1000x650")
        self.images = []
        self.index = 0
        self.slideshow = False
        self.slideshow_job = None
        self.anim_job = None
        self.current_frames = []
        self.current_frame_index = 0

        self._load_metadata()
        self._load_images()

        self._build_ui()
        self._show_image(0)

        self.root.bind("<Left>", lambda e: self.prev_image())
        self.root.bind("<Right>", lambda e: self.next_image())
        self.root.bind("<space>", lambda e: self.toggle_slideshow())

    def _load_metadata(self):
        self.metadata = {}
        if os.path.exists(METADATA_FILE):
            try:
                with open(METADATA_FILE, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            except Exception as e:
                messagebox.showwarning("Metadata", f"Failed to load metadata.json: {e}")
        else:
            # write a small example if not present
            example = {
                "example.png": {"name": "Example Character", "desc": "Add your own metadata.json to customize this panel."}
            }
            try:
                with open(METADATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(example, f, indent=2)
            except Exception:
                pass

    def _load_images(self):
        if not os.path.isdir(IMAGES_DIR):
            os.makedirs(IMAGES_DIR, exist_ok=True)
        patterns = ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp"]
        files = []
        for p in patterns:
            files.extend(glob.glob(os.path.join(IMAGES_DIR, p)))
        files.sort()
        self.images = [ImageItem(path, self.metadata.get(os.path.basename(path))) for path in files]

    def _build_ui(self):
        # main frames
        left = tk.Frame(self.root)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = tk.Frame(self.root, width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        # canvas for image
        self.canvas = tk.Label(left, text="No images found.\nPlace images in the 'images/' folder.", anchor="center", justify="center")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # controls
        ctrl = tk.Frame(left)
        ctrl.pack(fill=tk.X, padx=8, pady=(0,8))

        btn_prev = tk.Button(ctrl, text="◀ Prev", command=self.prev_image)
        btn_prev.pack(side=tk.LEFT)

        btn_next = tk.Button(ctrl, text="Next ▶", command=self.next_image)
        btn_next.pack(side=tk.LEFT, padx=(6,0))

        btn_slideshow = tk.Button(ctrl, text="Play ▶", command=self.toggle_slideshow)
        btn_slideshow.pack(side=tk.LEFT, padx=(6,0))
        self.btn_slideshow = btn_slideshow

        btn_open = tk.Button(ctrl, text="Open Folder", command=self.open_folder)
        btn_open.pack(side=tk.RIGHT)

        # right info panel
        tk.Label(right, text="Info", font=("Segoe UI", 12, "bold")).pack(anchor="nw", padx=8, pady=(8,0))
        self.info_name = tk.Label(right, text="", font=("Segoe UI", 11, "bold"), wraplength=300, justify="left")
        self.info_name.pack(anchor="nw", padx=8, pady=(4,0))
        self.info_desc = tk.Label(right, text="", wraplength=300, justify="left")
        self.info_desc.pack(anchor="nw", padx=8, pady=(6,8))

        tk.Label(right, text="Controls", font=("Segoe UI", 10, "bold")).pack(anchor="nw", padx=8, pady=(10,2))
        tk.Label(right, text="← / → : Prev / Next\nSpace : Play/Pause slideshow\nClick image to toggle full size", justify="left").pack(anchor="nw", padx=8)

        # footer
        self.status = tk.Label(self.root, text="", bd=1, relief=tk.SUNKEN, anchor="w")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        # click to toggle scaling
        self.canvas.bind("<Button-1>", lambda e: self._toggle_fullscreen_image())

    def _toggle_fullscreen_image(self):
        # toggle between fit-in-window and native size by resizing label
        if not self.images:
            return
        item = self.images[self.index]
        try:
            img = Image.open(item.path)
        except Exception:
            return
        w, h = img.size
        # make a new top-level window to show native resolution
        top = tk.Toplevel(self.root)
        top.title(os.path.basename(item.path))
        top.geometry(f"{w}x{h}")
        lbl = tk.Label(top)
        lbl.pack()
        # show native image
        photo = ImageTk.PhotoImage(img)
        lbl.img = photo
        lbl.config(image=photo)

    def open_folder(self):
        folder = filedialog.askdirectory(initialdir=IMAGES_DIR, title="Select images folder")
        if folder:
            global IMAGES_DIR
            IMAGES_DIR = folder
            self._load_metadata()
            self._load_images()
            if not self.images:
                self.canvas.config(text="No images found in that folder.")
            else:
                self.index = 0
                self._show_image(0)

    def _show_image(self, idx):
        if not self.images:
            self.canvas.config(text="No images found. Put images in the 'images/' folder.")
            self.info_name.config(text="")
            self.info_desc.config(text="")
            self.status.config(text="0 images")
            return

        self._stop_animation()
        self.index = idx % len(self.images)
        item = self.images[self.index]

        # compute available size for thumbnail
        max_w = max(200, self.root.winfo_width() - 360)  # leave space for side panel
        max_h = max(200, self.root.winfo_height() - 120)
        maxsize = (max_w, max_h)

        frames = item.get_frames(maxsize)
        if not frames:
            self.canvas.config(text="Failed to load image.")
            return

        self.current_frames = frames
        self.current_frame_index = 0
        self.canvas.config(image=frames[0])
        self.canvas.image = frames[0]  # keep reference
        self.status.config(text=f"{self.index+1}/{len(self.images)} — {os.path.basename(item.path)}")

        meta = item.meta or {}
        self.info_name.config(text=meta.get("name", os.path.basename(item.path)))
        self.info_desc.config(text=meta.get("desc", "No description available."))

        if item._is_animated and len(frames) > 1:
            # schedule animation
            self._animate_gif()

    def _animate_gif(self):
        if not self.current_frames:
            return
        # display current frame and advance
        frame = self.current_frames[self.current_frame_index]
        self.canvas.config(image=frame)
        self.canvas.image = frame
        self.current_frame_index = (self.current_frame_index + 1) % len(self.current_frames)
        # schedule next
        self.anim_job = self.root.after(100, self._animate_gif)  # 100 ms between frames (approx)

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

def main():
    root = tk.Tk()
    app = ViewerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
