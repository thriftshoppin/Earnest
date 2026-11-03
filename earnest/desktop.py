"""Earnest's local desktop workspace. Processing remains in the CLI/engine."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent / "earnest"
DEFAULT = ROOT / "results" / "Union-Stairs"
BG, PANEL, FIELD, FG, MUTED, ACCENT = "#11151a", "#1b222a", "#262f38", "#eef0ed", "#9ca9ad", "#e4b073"


class Desktop(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Earnest | Audio intelligence")
        self.geometry("1240x820")
        self.minsize(1000, 700)
        self.configure(bg=BG)
        self.events = queue.Queue()
        self.process = None
        self.vars = {}
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(18, 10), font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", FIELD)], foreground=[("selected", FG)])
        self._header()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=28, pady=(0, 10))
        self.analysis_tab()
        self.room_tab()
        self.data_tab()
        self.listen_tab()
        self.log = tk.Text(self, height=8, bg="#0b0f13", fg="#b5c4bd", insertbackground=FG,
                           relief="flat", font=("Consolas", 9), wrap="word", state="disabled")
        self.log.pack(fill="x", padx=28, pady=(0, 8))
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=28, pady=(0, 14))
        self.status = tk.StringVar(value="READY  /  Local engine")
        tk.Label(footer, textvariable=self.status, bg=BG, fg=ACCENT, font=("Segoe UI", 9)).pack(side="left")
        self.button(footer, "STOP CURRENT JOB", self.stop_job, secondary=True).pack(side="right")
        self.after(100, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _header(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=28, pady=(20, 18))
        tk.Label(bar, text="✦", bg=BG, fg=ACCENT, font=("Segoe UI Symbol", 26)).pack(side="left", padx=(0, 14))
        title = tk.Frame(bar, bg=BG)
        title.pack(side="left")
        tk.Label(title, text="E A R N E S T", bg=BG, fg=FG, font=("Segoe UI Semibold", 19)).pack(anchor="w")
        tk.Label(title, text="AUDIO INTELLIGENCE  /  LOCAL WORKSPACE", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(bar, text="ANALYZE  ·  MODEL  ·  LISTEN", bg=BG, fg=ACCENT, font=("Segoe UI", 10)).pack(side="right")

    def page(self, name, headline, sub):
        page = tk.Frame(self.notebook, bg=PANEL)
        self.notebook.add(page, text=name)
        body = tk.Frame(page, bg=PANEL, padx=30, pady=22)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=headline, bg=PANEL, fg=FG, font=("Segoe UI Semibold", 19)).pack(anchor="w")
        tk.Label(body, text=sub, bg=PANEL, fg=MUTED, font=("Segoe UI", 10), wraplength=1050, justify="left").pack(anchor="w", pady=(5, 18))
        return body

    def button(self, parent, label, action, secondary=False):
        return tk.Button(parent, text=label, command=action, bg=FIELD if secondary else ACCENT,
                         fg=FG if secondary else BG, activebackground="#d8a467", relief="flat",
                         padx=14, pady=7, font=("Segoe UI Semibold", 9), cursor="hand2")

    def field(self, parent, key, label, value="", kind=None):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, bg=PANEL, fg=FG, width=18, anchor="w", font=("Segoe UI", 10)).pack(side="left")
        var = self.vars[key] = tk.StringVar(value=str(value))
        tk.Entry(row, textvariable=var, bg=FIELD, fg=FG, insertbackground=FG, relief="flat", font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, ipady=7)
        if kind:
            self.button(row, "BROWSE", lambda: self.browse(var, kind), True).pack(side="left", padx=(8, 0))
        return var

    def browse(self, var, kind):
        value = filedialog.askdirectory() if kind == "folder" else filedialog.askopenfilename()
        if value:
            var.set(value)

    def analysis_tab(self):
        p = self.page("01  ANALYZE", "Understand the recording", "Compare a wet probe export with its matching dry reference. The trace below shows the actual engine output.")
        self.field(p, "wet", "Wet export", ORIGINAL / "inbox" / "union20.flac", "file")
        self.field(p, "dry", "Dry reference", ORIGINAL / "inbox" / "dry.flac", "file")
        self.field(p, "probe", "Original probe", ORIGINAL / "probe" / "earnest_probe_v1.flac", "file")
        self.field(p, "manifest", "Probe manifest", ORIGINAL / "probe" / "earnest_probe_v1.json", "file")
        self.field(p, "room_name", "Room / effect", "Union Stairs")
        self.field(p, "mix", "Known mix %", "20")
        self.field(p, "analysis_out", "Output folder", "", "folder")
        self.button(p, "ANALYZE PAIR  →", self.analyze).pack(anchor="w", pady=16)
        tk.Label(p, text="For this analyzer, use the matching probe exports. Song pairs are training material; they are not probe measurements.", bg=PANEL, fg=MUTED, wraplength=1000, justify="left").pack(anchor="w")

    def room_tab(self):
        p = self.page("02  ROOMS", "Turn evidence into a room", "Fit measured decay to an editable room, then use the resulting room in Earnest. Geometry remains an assumption.")
        self.field(p, "base_room", "Base room", ROOT / "inbox" / "rooms" / "Union-Stairs.room.json", "file")
        self.field(p, "formula", "Analysis formula", DEFAULT / "analysis" / "union20" / "step_mix20" / "formula.json", "file")
        self.field(p, "fit_out", "New output folder", "", "folder")
        self.button(p, "FIT ROOM  →", self.fit).pack(anchor="w", pady=16)
        self.field(p, "kit_out", "New capture folder", "", "folder")
        self.button(p, "CREATE CAPTURE KIT", self.kit, True).pack(anchor="w", pady=12)
        tk.Label(p, text="Fit uses octave-band decay; it does not recover the original room geometry or all plugin behavior.", bg=PANEL, fg=MUTED, wraplength=1000, justify="left").pack(anchor="w")

    def data_tab(self):
        p = self.page("03  DATA & MODELS", "Build a learning library", "Register matched dry / wet songs or stems with their settings. Original audio stays where it is.")
        self.field(p, "data_dry", "Dry audio", "", "file")
        self.field(p, "data_wet", "Wet audio", "", "file")
        self.field(p, "data_name", "Source name", "")
        self.field(p, "data_effect", "Effect / preset", "Union Stairs")
        self.field(p, "data_mix", "Mix % if known", "")
        self.field(p, "data_split", "Split", "train")
        self.button(p, "SAVE PAIR TO LIBRARY", self.save_pair).pack(anchor="w", pady=14)
        tk.Label(p, text="MODEL TRAINING  /  NOT YET AVAILABLE", bg=PANEL, fg=ACCENT, font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(8, 2))
        tk.Label(p, text="These entries prepare a dataset. They do not train a model or check synchronization, levels, clipping, or audio quality.", bg=PANEL, fg=MUTED, wraplength=1000, justify="left").pack(anchor="w")
        self.button(p, "OPEN DATA LIBRARY", self.open_library, True).pack(anchor="w", pady=12)

    def listen_tab(self):
        p = self.page("04  LISTEN", "Hear the room", "Use the StageJack shell for the existing live route, or render and audition a room preview.")
        self.field(p, "preview_room", "Room file", ROOT / "inbox" / "rooms" / "Union-Stairs.room.json", "file")
        row = tk.Frame(p, bg=PANEL)
        row.pack(anchor="w", pady=16)
        self.button(row, "RENDER ROOM PREVIEW", self.preview).pack(side="left", padx=(0, 10))
        self.button(row, "OPEN STAGEJACK CONTROLS", self.stagejack, True).pack(side="left")
        tk.Label(p, text="The live route is experimental and may have a parallel dry path. Opening controls does not start another audio bridge.", bg=PANEL, fg=MUTED, wraplength=1000, justify="left").pack(anchor="w")

    def get(self, key):
        return self.vars[key].get().strip()

    def require(self, keys):
        for key in keys:
            if not self.get(key):
                raise ValueError("Please fill in " + key.replace("_", " ") + ".")

    def safe(self, action):
        try:
            action()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Earnest", str(exc), parent=self)

    def analyze(self):
        def action():
            self.require(["wet", "dry", "probe", "manifest", "room_name"])
            args = ["analyze", self.get("wet"), "--dry", self.get("dry"), "--probe", self.get("probe"), "--manifest", self.get("manifest"), "--room", self.get("room_name")]
            if self.get("mix"):
                n = int(self.get("mix"))
                if not 0 <= n <= 100: raise ValueError("Mix must be between 0 and 100.")
                args += ["--mix", str(n)]
            if self.get("analysis_out"): args += ["--out", self.get("analysis_out")]
            self.run_job(args)
        self.safe(action)

    def fit(self):
        def action():
            self.require(["base_room", "formula"])
            args = ["room-solve-from-analysis", self.get("base_room"), self.get("formula")]
            if self.get("fit_out"): args += ["--out", self.get("fit_out")]
            self.run_job(args)
        self.safe(action)

    def kit(self):
        def action():
            self.require(["kit_out", "room_name"])
            self.run_job(["capture-kit", "--out", self.get("kit_out"), "--room", self.get("room_name")])
        self.safe(action)

    def preview(self):
        def action():
            self.require(["preview_room"])
            self.run_job(["room-preview", self.get("preview_room"), "--play"])
        self.safe(action)

    def save_pair(self):
        def action():
            self.require(["data_dry", "data_wet", "data_name", "data_effect", "data_split"])
            dry, wet = Path(self.get("data_dry")).resolve(), Path(self.get("data_wet")).resolve()
            if not dry.is_file() or not wet.is_file() or dry == wet: raise ValueError("Choose two different existing audio files.")
            split = self.get("data_split").lower()
            if split not in ("train", "validation", "test"): raise ValueError("Split must be train, validation, or test.")
            mix = self.get("data_mix")
            if mix and not 0 <= float(mix) <= 100: raise ValueError("Mix must be between 0 and 100.")
            root = ROOT / "data" / "desktop-library"
            root.mkdir(parents=True, exist_ok=True)
            path = root / "pairs.jsonl"
            row = {"schema": "earnest.pair.v1", "source": self.get("data_name"), "dry": str(dry), "wet": str(wet), "effect": self.get("data_effect"), "mix_percent": float(mix) if mix else None, "split": split}
            with path.open("a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.write_log("Saved pair to " + str(path) + "\n")
            messagebox.showinfo("Earnest", "Pair added to the local library. No model has been trained.", parent=self)
        self.safe(action)

    def open_library(self):
        path = ROOT / "data" / "desktop-library"
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def stagejack(self):
        path = ROOT / "stagejack" / "StageJack-Earnest.exe"
        if not path.is_file():
            messagebox.showerror("Earnest", "StageJack controls were not found at " + str(path), parent=self)
            return
        # Do not start another controller while the existing one owns a route.
        found = subprocess.run(["tasklist", "/FI", "IMAGENAME eq StageJack-Earnest.exe", "/NH"],
                               capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if "stagejack-earnest.exe" in found.stdout.lower():
            messagebox.showinfo("StageJack", "StageJack is already open. Use its existing window to avoid overlapping audio routes.", parent=self)
            return
        env = os.environ.copy()
        env["EARNEST_HOME"] = str(ROOT)
        subprocess.Popen([str(path)], cwd=str(path.parent), env=env)

    def run_job(self, args):
        if self.process and self.process.poll() is None:
            raise ValueError("A job is already running. Wait for it or stop it first.")
        command = [sys.executable, "-u", "-m", "earnest", *args]
        self.write_log("\n> " + subprocess.list2cmdline(command) + "\n")
        self.process = subprocess.Popen(command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        process = self.process
        self.status.set("WORKING  /  " + args[0])
        def read():
            for line in process.stdout: self.events.put(("line", line))
            self.events.put(("done", process.wait()))
        threading.Thread(target=read, daemon=True).start()

    def stop_job(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.write_log("Stop requested.\n")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "line": self.write_log(value)
                else:
                    self.status.set("READY  /  Job exited " + str(value))
                    self.write_log("\nJob exited " + str(value) + "\n")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("Earnest", "Stop the current job and close?", parent=self): return
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    Desktop().mainloop()
