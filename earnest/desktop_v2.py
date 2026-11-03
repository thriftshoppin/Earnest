"""Local desktop interface for Earnest's existing analysis and room tools."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
from tkinterdnd2 import DND_FILES, TkinterDnD

BG = "#0d1419"
SIDE = "#111d22"
CARD = "#19272b"
LINE = "#294043"
TEXT = "#e8eee9"
DIM = "#9bb0a8"
MINT = "#a3e0b8"
GOLD = "#dbbd83"
AUDIO = (("Audio files", "*.wav *.flac *.aif *.aiff"), ("All files", "*.*"))
JSON = (("JSON files", "*.json"), ("All files", "*.*"))
INBOX = ROOT / "inbox"
RESULTS = ROOT / "results"
REFERENCE = ROOT / "reference"


def unique_dir(parent, label):
    name = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + label + "-" + uuid.uuid4().hex[:6]
    return parent / name


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Earnest")
        self.geometry("1220x840")
        self.minsize(1000, 720)
        self.configure(bg=BG)
        self.jobs = queue.Queue()
        self.process = None
        self.inputs = {}
        self.labels = {}
        self.pages = {}
        self.nav = {}
        self.after_job = None
        for folder in [INBOX / "analysis" / "dry", INBOX / "analysis" / "wet", INBOX / "rooms" / "imports",
                       INBOX / "training" / "dry", INBOX / "training" / "wet", RESULTS / "analysis",
                       RESULTS / "rooms", RESULTS / "capture-kits", RESULTS / "previews", ROOT / "data"]:
            folder.mkdir(parents=True, exist_ok=True)
        self.shell()
        self.analysis_page()
        self.rooms_page()
        self.data_page()
        self.listen_page()
        self.show("analysis")
        self.after(100, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def shell(self):
        left = tk.Frame(self, bg=SIDE, width=205)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="✦", bg=SIDE, fg=MINT, font=("Segoe UI Symbol", 29)).pack(anchor="w", padx=22, pady=(24, 0))
        tk.Label(left, text="EARNEST", bg=SIDE, fg=TEXT, font=("Segoe UI Semibold", 20)).pack(anchor="w", padx=22)
        tk.Label(left, text="AUDIO WORKSPACE", bg=SIDE, fg=DIM, font=("Segoe UI", 8)).pack(anchor="w", padx=22, pady=(1, 30))
        for key, name in [("analysis", "01   Analyze"), ("rooms", "02   Rooms"), ("data", "03   Training data"), ("listen", "04   Listen")]:
            b = tk.Button(left, text=name, command=lambda k=key: self.show(k), anchor="w", relief="flat", bd=0,
                          bg=SIDE, fg=DIM, activebackground=CARD, activeforeground=TEXT,
                          font=("Segoe UI Semibold", 10), padx=20, pady=13, cursor="hand2")
            b.pack(fill="x", padx=8, pady=2)
            self.nav[key] = b
        tk.Label(left, text="LOCAL  /  YOUR FILES", bg=SIDE, fg=DIM, font=("Segoe UI", 8)).pack(side="bottom", anchor="w", padx=22, pady=23)
        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        top = tk.Frame(right, bg=BG)
        top.pack(fill="x", padx=30, pady=(22, 10))
        tk.Label(top, text="YOUR SOUND, UNDERSTOOD", bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(side="left")
        self.state = tk.StringVar(value="●  READY")
        tk.Label(top, textvariable=self.state, bg=BG, fg=MINT, font=("Segoe UI Semibold", 9)).pack(side="right")
        self.container = tk.Frame(right, bg=BG)
        self.container.pack(fill="both", expand=True, padx=30)
        bottom = tk.Frame(right, bg=BG)
        bottom.pack(fill="x", padx=30, pady=(8, 20))
        labelrow = tk.Frame(bottom, bg=BG)
        labelrow.pack(fill="x")
        tk.Label(labelrow, text="ACTIVITY", bg=BG, fg=DIM, font=("Segoe UI Semibold", 9)).pack(side="left")
        tk.Button(labelrow, text="STOP JOB", command=self.stop, bg=BG, fg=DIM, relief="flat", font=("Segoe UI", 9)).pack(side="right")
        self.log = tk.Text(bottom, height=6, bg="#0a1114", fg="#afc4b7", insertbackground=TEXT,
                           relief="flat", font=("Consolas", 9), wrap="word", state="disabled", padx=10, pady=8)
        self.log.pack(fill="x")

    def page(self, key, eyebrow, title, description):
        p = tk.Frame(self.container, bg=BG)
        self.pages[key] = p
        tk.Label(p, text=eyebrow, bg=BG, fg=GOLD, font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        tk.Label(p, text=title, bg=BG, fg=TEXT, font=("Segoe UI Semibold", 25)).pack(anchor="w")
        tk.Label(p, text=description, bg=BG, fg=DIM, font=("Segoe UI", 10), wraplength=850, justify="left").pack(anchor="w", pady=(5, 16))
        return p

    def show(self, key):
        for k, p in self.pages.items():
            p.pack_forget()
            self.nav[k].configure(bg=CARD if k == key else SIDE, fg=MINT if k == key else DIM)
        self.pages[key].pack(fill="both", expand=True)

    def button(self, parent, text, command, secondary=False):
        return tk.Button(parent, text=text, command=command, bg=LINE if secondary else MINT,
                         fg=TEXT if secondary else BG, activebackground="#c2ead0", activeforeground=BG,
                         relief="flat", padx=15, pady=9, font=("Segoe UI Semibold", 9), cursor="hand2")

    def drop(self, parent, key, title, subtitle, target, types=AUDIO):
        box = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        box.pack(fill="x", pady=5)
        text = tk.Frame(box, bg=CARD)
        text.pack(side="left", fill="x", expand=True, padx=16, pady=10)
        heading = tk.Label(text, text=title, bg=CARD, fg=TEXT, font=("Segoe UI Semibold", 11))
        heading.pack(anchor="w")
        name = tk.StringVar(value=subtitle)
        self.labels[key] = name
        caption = tk.Label(text, textvariable=name, bg=CARD, fg=DIM, font=("Segoe UI", 9), anchor="w")
        caption.pack(fill="x", pady=(3, 0))
        self.button(box, "BROWSE", lambda: self.browse(key, target, types), True).pack(side="right", padx=14)
        def dropped(event):
            try:
                files = self.tk.splitlist(event.data)
                if len(files) != 1: raise ValueError("Drop one file into each box.")
                self.import_file(key, Path(files[0]), target, types)
            except (ValueError, OSError) as exc: messagebox.showerror("Earnest", str(exc), parent=self)
        for widget in (box, text, heading, caption):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", dropped)

    def browse(self, key, target, types):
        name = filedialog.askopenfilename(parent=self, filetypes=types)
        if name:
            try: self.import_file(key, Path(name), target, types)
            except (ValueError, OSError) as exc: messagebox.showerror("Earnest", str(exc), parent=self)

    def import_file(self, key, source, target, types):
        if not source.is_file(): raise ValueError("That file is not available.")
        allowed = {".json"} if types == JSON else {".wav", ".flac", ".aif", ".aiff"}
        if source.suffix.lower() not in allowed: raise ValueError("Choose a supported " + ("JSON" if types == JSON else "audio") + " file.")
        dest = target / (uuid.uuid4().hex[:10] + "-" + source.name)
        shutil.copy2(source, dest)
        self.inputs[key] = dest
        self.labels[key].set(source.name + "   ·   added to Earnest")
        self.write("Added " + source.name + " → " + str(dest) + "\n")

    def info(self, parent, text):
        tk.Label(parent, text=text, bg=BG, fg=DIM, wraplength=830, justify="left", font=("Segoe UI", 9)).pack(anchor="w", pady=8)

    def row(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(14, 5))
        return row

    def analysis_page(self):
        p = self.page("analysis", "01  /  MEASURE", "Analyze a room", "Drop in a dry and wet export of the built-in probe. Earnest compares them and saves a new analysis automatically.")
        self.drop(p, "dry", "01  Dry reference", "Drop one audio file here or browse", INBOX / "analysis" / "dry")
        self.drop(p, "wet", "02  Processed export", "Drop the matching wet audio here or browse", INBOX / "analysis" / "wet")
        options = tk.Frame(p, bg=BG)
        options.pack(fill="x", pady=12)
        tk.Label(options, text="ROOM / EFFECT", bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(side="left")
        self.room_name = tk.StringVar(value="Union Stairs")
        tk.Entry(options, textvariable=self.room_name, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat", width=23, font=("Segoe UI", 10)).pack(side="left", padx=(10, 24), ipady=5)
        tk.Label(options, text="MIX %  (OPTIONAL)", bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(side="left")
        self.mix = tk.StringVar()
        tk.Entry(options, textvariable=self.mix, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat", width=6, font=("Segoe UI", 10)).pack(side="left", padx=10, ipady=5)
        r = self.row(p)
        self.button(r, "ANALYZE PAIR  →", self.analyze).pack(side="left")
        self.button(r, "OPEN ANALYSES", lambda: os.startfile(str(RESULTS / "analysis")), True).pack(side="left", padx=10)
        self.info(p, "Uses the included original Earnest probe. For songs, add matched pairs under Training data instead.")

    def rooms_page(self):
        p = self.page("rooms", "02  /  SHAPE", "Build a room", "Choose an analysis formula and fit it to the included Union room. Each result is saved in its own folder.")
        self.drop(p, "formula", "Analysis formula", "Drop formula.json here or browse", INBOX / "rooms" / "imports", JSON)
        default = RESULTS / "Union-Stairs" / "analysis" / "union20" / "step_mix20" / "formula.json"
        if default.is_file():
            self.inputs["formula"] = default
            self.labels["formula"].set("Union Stairs 20% analysis   ·   ready to use")
        self.info(p, "The room geometry is an editable assumption. The fit uses measured band decay; it does not reproduce every detail of the original effect.")
        r = self.row(p)
        self.button(r, "FIT ROOM  →", self.fit).pack(side="left")
        self.button(r, "OPEN ROOMS", lambda: os.startfile(str(RESULTS / "rooms")), True).pack(side="left", padx=10)
        self.button(r, "CREATE PROBE KIT", self.kit, True).pack(side="left")
        self.info(p, "Capture kits go to results / capture-kits, with instructions and a fresh probe inside.")

    def data_page(self):
        p = self.page("data", "03  /  LEARN", "Prepare training data", "Add a matching dry and processed song or stem. Earnest stores a copy of each and records the pair locally.")
        self.drop(p, "train_dry", "01  Dry audio", "Drop one source file here or browse", INBOX / "training" / "dry")
        self.drop(p, "train_wet", "02  Processed audio", "Drop its matching processed file here or browse", INBOX / "training" / "wet")
        row = tk.Frame(p, bg=BG)
        row.pack(fill="x", pady=12)
        tk.Label(row, text="SOURCE NAME", bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(side="left")
        self.source_name = tk.StringVar()
        tk.Entry(row, textvariable=self.source_name, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat", width=24).pack(side="left", padx=10, ipady=5)
        tk.Label(row, text="SPLIT", bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))
        self.split = tk.StringVar(value="train")
        ttk.Combobox(row, textvariable=self.split, values=("train", "validation", "test"), state="readonly", width=12).pack(side="left", padx=10)
        r = self.row(p)
        self.button(r, "SAVE PAIR  →", self.save_pair).pack(side="left")
        self.button(r, "OPEN TRAINING FILES", lambda: os.startfile(str(INBOX / "training")), True).pack(side="left", padx=10)
        self.info(p, "Model training is not built yet. Saving pairs prepares the library; it does not train or verify alignment or clipping.")

    def listen_page(self):
        p = self.page("listen", "04  /  AUDITION", "Listen to the room", "Preview a room or open the existing StageJack controls. Live routing remains experimental.")
        self.drop(p, "listen_room", "Room file", "Drop a room JSON file here or browse", INBOX / "rooms" / "imports", JSON)
        self.inputs["listen_room"] = INBOX / "rooms" / "Union-Stairs.room.json"
        self.labels["listen_room"].set("Union Stairs listening room   ·   ready to use")
        r = self.row(p)
        self.button(r, "RENDER & PLAY PREVIEW", self.preview).pack(side="left")
        self.button(r, "OPEN STAGEJACK", self.stagejack, True).pack(side="left", padx=10)
        self.info(p, "A preview plays on your Windows default output. StageJack may have a parallel dry path; its existing route is independent of this window.")

    def require(self, *keys):
        for key in keys:
            if key not in self.inputs or not self.inputs[key].is_file():
                raise ValueError("Add the " + key.replace("train_", "").replace("_", " ") + " file first.")

    def action(self, fn):
        try: fn()
        except (ValueError, OSError) as exc: messagebox.showerror("Earnest", str(exc), parent=self)

    def analyze(self):
        def run():
            self.require("dry", "wet")
            probe = REFERENCE / "earnest_probe_v1.flac"
            manifest = REFERENCE / "earnest_probe_v1.json"
            if not probe.is_file() or not manifest.is_file(): raise ValueError("The included probe or manifest is missing from the reference folder.")
            args = ["analyze", str(self.inputs["wet"]), "--dry", str(self.inputs["dry"]), "--probe", str(probe), "--manifest", str(manifest), "--room", self.room_name.get().strip() or "Room", "--out", str(unique_dir(RESULTS / "analysis", "analysis"))]
            if self.mix.get().strip():
                n = int(self.mix.get())
                if not 0 <= n <= 100: raise ValueError("Mix must be between 0 and 100.")
                args.extend(["--mix", str(n)])
            self.run_job(args)
        self.action(run)

    def fit(self):
        def run():
            self.require("formula")
            out = unique_dir(RESULTS / "rooms", "room")
            self.run_job(["room-solve-from-analysis", str(INBOX / "rooms" / "Union-Stairs.room.json"), str(self.inputs["formula"]), "--out", str(out)], ("room", out))
        self.action(run)

    def kit(self):
        self.action(lambda: self.run_job(["capture-kit", "--out", str(unique_dir(RESULTS / "capture-kits", "kit")), "--room", self.room_name.get().strip() or "Room"]))

    def preview(self):
        def run():
            self.require("listen_room")
            out = RESULTS / "previews" / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6] + ".wav")
            self.run_job(["room-preview", str(self.inputs["listen_room"]), "--out", str(out), "--play"])
        self.action(run)

    def save_pair(self):
        def save():
            self.require("train_dry", "train_wet")
            name = self.source_name.get().strip()
            if not name: raise ValueError("Enter a source name for this pair.")
            row = {"schema": "earnest.pair.v1", "source": name, "dry": str(self.inputs["train_dry"]), "wet": str(self.inputs["train_wet"]), "effect": self.room_name.get().strip(), "split": self.split.get()}
            with (ROOT / "data" / "pairs.jsonl").open("a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.write("Saved pair: " + name + "\n")
            messagebox.showinfo("Earnest", "Pair saved. Model training is not available yet.", parent=self)
        self.action(save)

    def stagejack(self):
        path = ROOT / "stagejack" / "StageJack-Earnest.exe"
        if not path.is_file():
            messagebox.showerror("Earnest", "StageJack controls are missing.", parent=self); return
        found = subprocess.run(["tasklist", "/FI", "IMAGENAME eq StageJack-Earnest.exe", "/NH"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if "stagejack-earnest.exe" in found.stdout.lower():
            messagebox.showinfo("Earnest", "StageJack is already open. Use the existing window to avoid overlapping routes.", parent=self); return
        env = os.environ.copy(); env["EARNEST_HOME"] = str(ROOT)
        subprocess.Popen([str(path)], cwd=str(path.parent), env=env)

    def run_job(self, args, after=None):
        if self.process and self.process.poll() is None: raise ValueError("Wait for the current job or stop it first.")
        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe": python = python.with_name("python.exe")
        cmd = [str(python), "-u", "-m", "earnest", *args]
        self.write("\nStarting " + args[0] + "...\n")
        self.process = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.after_job = after
        process = self.process
        self.state.set("●  WORKING")
        def read():
            for line in process.stdout: self.jobs.put(("line", line))
            self.jobs.put(("done", process.wait()))
        threading.Thread(target=read, daemon=True).start()

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate(); self.write("Stop requested.\n")

    def poll(self):
        try:
            while True:
                kind, value = self.jobs.get_nowait()
                if kind == "line": self.write(value)
                else:
                    self.state.set("●  READY" if value == 0 else "●  JOB STOPPED / ERROR")
                    self.write("\nFinished with exit code " + str(value) + "\n")
                    if value == 0 and self.after_job and self.after_job[0] == "room":
                        room = self.after_job[1] / "calibrated.room.json"
                        if room.is_file():
                            self.inputs["listen_room"] = room
                            self.labels["listen_room"].set("New fitted room   ·   ready to preview")
                    self.after_job = None
        except queue.Empty: pass
        self.after(100, self.poll)

    def write(self, text):
        self.log.configure(state="normal"); self.log.insert("end", text); self.log.see("end"); self.log.configure(state="disabled")

    def close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("Earnest", "Stop the current job and close?", parent=self): return
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
