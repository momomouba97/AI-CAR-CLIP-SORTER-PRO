# -*- coding: utf-8 -*-
"""
AI CAR CLIP SORTER PRO - Native macOS edition
Local folders, scene splitting, looping preview, manual classification and undo.
"""
import os, sys, re, json, shutil, threading, subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
from PIL import Image, ImageTk
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector, AdaptiveDetector
from scenedetect.frame_timecode import FrameTimecode
import imageio_ffmpeg

APP_NAME = "AI CAR CLIP SORTER PRO"
VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")

def app_data_dir():
    base = os.path.expanduser("~/Library/Application Support/AICarClipSorter")
    os.makedirs(base, exist_ok=True)
    return base

def natural_key(value):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", value)]

class CarClipSorter:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1180x800")
        self.root.minsize(960, 680)
        self.root.configure(bg="#10151d")

        self.base_dir = os.path.expanduser("~/Movies/AI CAR CLIP SORTER")
        self._ensure_folders()
        self.settings_file = os.path.join(app_data_dir(), "settings.json")
        self.settings = self.read_settings()
        self.clips_output_dir = self.settings.get("clips_output_dir") or os.path.join(self.base_dir, "ClipsCars")
        os.makedirs(self.clips_output_dir, exist_ok=True)
        self.state_file = os.path.join(app_data_dir(), "state.json")
        self.state = self.read_state()

        self.queue = []
        self.index = 0
        self.current_video = None
        self.cap = None
        self.playing = False
        self.frame_job = None
        self.photo = None
        self.scenes = []
        self.source_video = None
        self.busy = False
        self.progress_value = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="جاهز — اختر فيديو للبدء")
        self.progress_detail = tk.StringVar(value="لا توجد عملية قيد التنفيذ")

        self._style()
        self._build_ui()
        self.refresh_stats()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        style = ttk.Style()
        try: style.theme_use("clam")
        except Exception: pass
        bg, panel, panel2 = "#0b1220", "#131f31", "#1b2b42"
        text, muted, accent = "#edf4ff", "#9eb0c8", "#3478f6"
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("Card.TFrame", background=panel2)
        style.configure("TLabel", background=bg, foreground=text, font=("Arial", 11))
        style.configure("Panel.TLabel", background=panel, foreground=text, font=("Arial", 10))
        style.configure("Card.TLabel", background=panel2, foreground=text, font=("Arial", 10))
        style.configure("Title.TLabel", background=bg, foreground="#ffffff", font=("Arial", 23, "bold"))
        style.configure("Sub.TLabel", background=bg, foreground=muted, font=("Arial", 10))
        style.configure("Section.TLabel", background=bg, foreground="#dce8fa", font=("Arial", 13, "bold"))
        style.configure("TButton", font=("Arial", 10, "bold"), padding=(12, 9), background="#263750", foreground=text, borderwidth=0)
        style.map("TButton", background=[("active", "#354d6d"), ("disabled", "#202b3a")])
        for name, color, active in [("Accent", accent, "#2563d8"), ("Green", "#16865c", "#11734e"), ("Orange", "#bd7b21", "#a96817"), ("Red", "#b83d50", "#982e40")]:
            style.configure(f"{name}.TButton", background=color, foreground="white")
            style.map(f"{name}.TButton", background=[("active", active), ("disabled", "#344054")])
        style.configure("TNotebook", background=bg, borderwidth=0, tabmargins=(3, 5, 3, 0))
        style.configure("TNotebook.Tab", background=panel, foreground=muted, padding=(18, 10), font=("Arial", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", accent)], foreground=[("selected", "#ffffff")])
        style.configure("Treeview", background=panel, fieldbackground=panel, foreground=text, rowheight=29, borderwidth=0, font=("Arial", 10))
        style.configure("Treeview.Heading", background=panel2, foreground=text, padding=8, font=("Arial", 10, "bold"))
        style.map("Treeview", background=[("selected", "#2459a8")])
        style.configure("Horizontal.TProgressbar", troughcolor="#26364c", background="#35a879", bordercolor="#26364c", lightcolor="#35a879", darkcolor="#35a879", thickness=13)

    def _ensure_folders(self):
        for name in ("ClipsCars", "MovingCars", "StoppingCars", "ExcludedCars"):
            os.makedirs(os.path.join(self.base_dir, name), exist_ok=True)

    def folder(self, name):
        return os.path.join(self.base_dir, name)

    def read_settings(self):
        try:
            with open(os.path.join(app_data_dir(), "settings.json"), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_settings(self):
        with open(self.settings_file, "w", encoding="utf-8") as f:
            json.dump({"clips_output_dir": self.clips_output_dir}, f, ensure_ascii=False, indent=2)

    def read_state(self):
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("skipped", [])
            data.setdefault("history", [])
            return data
        except Exception:
            return {"skipped": [], "history": []}

    def save_state(self):
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_file)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 16))
        title_row = ttk.Frame(header)
        title_row.pack(fill="x")
        ttk.Label(title_row, text="AI CAR CLIP SORTER PRO", style="Title.TLabel").pack(side="left")
        ttk.Label(title_row, text="MAC EDITION  •  INTEL", style="Sub.TLabel").pack(side="right", pady=9)
        ttk.Label(header, text="استوديو احترافي لتقسيم فيديوهات السيارات ومراجعة المقاطع وتصنيفها محلياً",
                  style="Sub.TLabel").pack(anchor="w", pady=(5, 0))

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.split_tab = ttk.Frame(self.tabs, padding=16)
        self.sort_tab = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(self.split_tab, text="  🎬  تقسيم الفيديو  ")
        self.tabs.add(self.sort_tab, text="  🚘  فرز المقاطع  ")
        self._build_splitter()
        self._build_sorter()

        # Persistent operation monitor
        monitor = ttk.Frame(outer, style="Panel.TFrame", padding=12)
        monitor.pack(fill="x", pady=(14, 0))
        top = ttk.Frame(monitor, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="مركز العمليات", style="Panel.TLabel", font=("Arial", 11, "bold")).pack(side="left")
        self.progress_percent = ttk.Label(top, text="0%", style="Panel.TLabel", font=("Arial", 10, "bold"))
        self.progress_percent.pack(side="right")
        self.progressbar = ttk.Progressbar(monitor, variable=self.progress_value, maximum=100, mode="determinate")
        self.progressbar.pack(fill="x", pady=9)
        ttk.Label(monitor, textvariable=self.progress_text, style="Panel.TLabel").pack(anchor="w")
        ttk.Label(monitor, textvariable=self.progress_detail, style="Panel.TLabel").pack(anchor="w", pady=(3, 0))
        logrow = ttk.Frame(monitor, style="Panel.TFrame")
        logrow.pack(fill="x", pady=(8, 0))
        self.log_text = tk.Text(logrow, height=3, bg="#0c1625", fg="#b9cbe3", insertbackground="white",
                                relief="flat", font=("Menlo", 9), wrap="word", padx=9, pady=7)
        self.log_text.pack(side="left", fill="x", expand=True)
        self.log_text.insert("end", "[جاهز] تم تشغيل التطبيق بنجاح.\n")
        self.log_text.configure(state="disabled")
        ttk.Button(logrow, text="مسح السجل", command=self.clear_log).pack(side="right", padx=(8, 0))

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        self.folder_label = ttk.Label(footer, text=f"مجلد العمل: {self.base_dir}", style="Sub.TLabel")
        self.folder_label.pack(side="left")
        ttk.Button(footer, text="تغيير مجلد العمل", command=self.choose_base).pack(side="right")

    def log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        def write():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{stamp}] {message}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, write)

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def update_progress(self, value=None, title=None, detail=None, mode="determinate"):
        def update():
            if mode == "indeterminate":
                if str(self.progressbar.cget("mode")) != "indeterminate":
                    self.progressbar.configure(mode="indeterminate")
                    self.progressbar.start(12)
                self.progress_percent.configure(text="…")
            else:
                if str(self.progressbar.cget("mode")) == "indeterminate":
                    self.progressbar.stop()
                    self.progressbar.configure(mode="determinate")
                if value is not None:
                    self.progress_value.set(max(0, min(100, value)))
                    self.progress_percent.configure(text=f"{int(value)}%")
            if title is not None: self.progress_text.set(title)
            if detail is not None: self.progress_detail.set(detail)
        self.root.after(0, update)

    def _build_splitter(self):
        tab = self.split_tab
        source_card = ttk.Frame(tab, style="Panel.TFrame", padding=13)
        source_card.pack(fill="x", pady=(0, 10))
        ttk.Label(source_card, text="1. ملف الفيديو المصدر", style="Panel.TLabel", font=("Arial", 11, "bold")).pack(anchor="w")
        top = ttk.Frame(source_card, style="Panel.TFrame")
        top.pack(fill="x", pady=(9, 0))
        ttk.Button(top, text="اختيار الفيديو الأصلي", style="Accent.TButton", command=self.choose_source).pack(side="left")
        self.source_label = ttk.Label(top, text="لم يتم اختيار فيديو", style="Panel.TLabel")
        self.source_label.pack(side="left", padx=12)

        output_card = ttk.Frame(tab, style="Panel.TFrame", padding=13)
        output_card.pack(fill="x", pady=(0, 10))
        ttk.Label(output_card, text="2. مكان حفظ المقاطع الناتجة", style="Panel.TLabel", font=("Arial", 11, "bold")).pack(anchor="w")
        outrow = ttk.Frame(output_card, style="Panel.TFrame")
        outrow.pack(fill="x", pady=(8, 0))
        self.output_btn = ttk.Button(outrow, text="اختيار مجلد الحفظ", command=self.choose_clips_output)
        self.output_btn.pack(side="left")
        self.output_label = ttk.Label(outrow, text=self.clips_output_dir, style="Panel.TLabel")
        self.output_label.pack(side="left", padx=12, fill="x", expand=True)

        controls = ttk.Frame(tab, style="Panel.TFrame", padding=14)
        controls.pack(fill="x", pady=4)
        ttk.Label(controls, text="3. إعدادات اكتشاف المشاهد", style="Panel.TLabel", font=("Arial", 11, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        ttk.Label(controls, text="حساسية اكتشاف المشاهد", style="Panel.TLabel").grid(row=1, column=0, sticky="w")
        self.sensitivity = tk.DoubleVar(value=12)
        ttk.Scale(controls, from_=8, to=40, variable=self.sensitivity, orient="horizontal").grid(row=2, column=0, sticky="ew", padx=(0, 18))
        self.sens_value = ttk.Label(controls, text="12", style="Panel.TLabel")
        self.sens_value.grid(row=2, column=1, sticky="w")
        self.sensitivity.trace_add("write", lambda *_: self.sens_value.configure(text=str(round(self.sensitivity.get(), 1))))
        ttk.Label(controls, text="أقصر مدة للمشهد (ثانية)", style="Panel.TLabel").grid(row=1, column=2, sticky="w")
        self.min_duration = tk.DoubleVar(value=0.15)
        ttk.Scale(controls, from_=0.10, to=3.0, variable=self.min_duration, orient="horizontal").grid(row=2, column=2, sticky="ew", padx=(0, 18))
        self.min_value = ttk.Label(controls, text="0.15", style="Panel.TLabel")
        self.min_value.grid(row=2, column=3, sticky="w")
        self.min_duration.trace_add("write", lambda *_: self.min_value.configure(text=f"{self.min_duration.get():.2f}"))
        self.adaptive = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="تفعيل الكاشف التكيفي لنتائج أكثر شمولاً", variable=self.adaptive).grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 0))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(2, weight=1)

        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=10)
        self.analyze_btn = ttk.Button(actions, text="تحليل الفيديو", style="Accent.TButton", command=self.analyze)
        self.analyze_btn.pack(side="left")
        self.export_btn = ttk.Button(actions, text="تصدير المقاطع إلى المجلد المحدد", style="Green.TButton", command=self.export_scenes, state="disabled")
        self.export_btn.pack(side="left", padx=8)
        self.split_status = tk.StringVar(value="اختر فيديو ومجلد حفظ ثم ابدأ التحليل.")
        ttk.Label(tab, textvariable=self.split_status, style="Sub.TLabel").pack(anchor="w", pady=5)
        ttk.Label(tab, text="المشاهد المكتشفة", style="Section.TLabel").pack(anchor="w", pady=(8, 5))
        columns = ("number", "start", "end", "duration")
        self.scene_tree = ttk.Treeview(tab, columns=columns, show="headings", height=7)
        for col, title, width in [("number", "رقم", 80), ("start", "البداية (ث)", 160), ("end", "النهاية (ث)", 160), ("duration", "المدة (ث)", 160)]:
            self.scene_tree.heading(col, text=title)
            self.scene_tree.column(col, width=width, anchor="center")
        self.scene_tree.pack(fill="both", expand=True, pady=5)

    def _build_sorter(self):
        tab = self.sort_tab
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Button(bar, text="🔄 تحميل المقاطع", style="Accent.TButton", command=self.load_queue).pack(side="left")
        ttk.Button(bar, text="↩ إعادة المقاطع المتجاوزة", command=self.reset_skipped).pack(side="left", padx=6)
        ttk.Button(bar, text="↶ تراجع عن آخر تصنيف", command=self.undo).pack(side="left")

        self.video_canvas = tk.Canvas(tab, bg="#05080c", highlightthickness=0, height=430)
        self.video_canvas.pack(fill="both", expand=True)
        self.video_canvas.bind("<Configure>", lambda e: self.show_frame_once())
        self.status = tk.StringVar(value="اضغط على تحميل المقاطع للبدء.")
        ttk.Label(tab, textvariable=self.status).pack(anchor="w", pady=8)

        self.exclude_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="نقل المقطع المتجاوز إلى ExcludedCars", variable=self.exclude_var).pack(anchor="w", pady=(0, 8))

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=4)
        ttk.Button(buttons, text="🚗 سيارة متحركة  (1)", style="Green.TButton",
                   command=lambda: self.classify("moving")).pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(buttons, text="🅿 سيارة متوقفة  (2)", style="Accent.TButton",
                   command=lambda: self.classify("stopping")).pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(buttons, text="⏭ تجاوز / استبعاد  (3)", style="Orange.TButton",
                   command=lambda: self.classify("skip")).pack(side="left", fill="x", expand=True, padx=3)

        self.stats = tk.StringVar()
        ttk.Label(tab, textvariable=self.stats, style="Sub.TLabel").pack(anchor="w", pady=12)
        self.root.bind("1", lambda e: self.classify("moving"))
        self.root.bind("2", lambda e: self.classify("stopping"))
        self.root.bind("3", lambda e: self.classify("skip"))
        self.root.bind("<Control-z>", lambda e: self.undo())

    def choose_base(self):
        chosen = filedialog.askdirectory(title="اختر مجلد العمل ومجلدات التصنيف")
        if not chosen: return
        self.stop_video()
        self.base_dir = chosen
        self._ensure_folders()
        self.folder_label.configure(text=f"مجلد العمل: {self.base_dir}")
        self.refresh_stats()
        self.log(f"تم تغيير مجلد العمل إلى: {chosen}")
        messagebox.showinfo(APP_NAME, "تم تغيير مجلد العمل. مجلد حفظ المقاطع المصدرية يبقى مستقلاً ويمكن تغييره من تبويب التقسيم.")

    def choose_clips_output(self):
        chosen = filedialog.askdirectory(title="اختر المجلد الذي ستحفظ فيه المقاطع", initialdir=self.clips_output_dir if os.path.isdir(self.clips_output_dir) else self.base_dir)
        if not chosen: return
        self.clips_output_dir = chosen
        os.makedirs(self.clips_output_dir, exist_ok=True)
        self.save_settings()
        self.output_label.configure(text=self.clips_output_dir)
        self.log(f"تم تحديد مجلد حفظ المقاطع: {chosen}")
        self.refresh_stats()

    def choose_source(self):
        path = filedialog.askopenfilename(
            title="اختر فيديو", filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"), ("All files", "*.*")]
        )
        if path:
            self.source_video = path
            self.source_label.configure(text=os.path.basename(path))
            self.split_status.set("الفيديو جاهز للتحليل.")
            self.export_btn.configure(state="disabled")

    def set_busy(self, busy, text=None):
        self.busy = busy
        self.analyze_btn.configure(state="disabled" if busy else "normal")
        if text: self.split_status.set(text)

    def analyze(self):
        if not self.source_video:
            messagebox.showwarning(APP_NAME, "اختر الفيديو الأصلي أولاً.")
            return
        self.analysis_source = self.source_video
        self.analysis_sensitivity = float(self.sensitivity.get())
        self.analysis_min_duration = float(self.min_duration.get())
        self.analysis_adaptive = bool(self.adaptive.get())
        self.set_busy(True, "جارٍ تحليل المشاهد... قد تستغرق العملية بعض الوقت.")
        self.update_progress(0, "بدء تحليل الفيديو", "قراءة خصائص الملف وتجهيز كواشف المشاهد", mode="indeterminate")
        self.log("بدأ تحليل الفيديو المصدر.")
        threading.Thread(target=self._analyze_worker, daemon=True).start()

    def _analyze_worker(self):
        try:
            self.log("المرحلة 1/3: قراءة معلومات الفيديو.")
            source_video = self.analysis_source
            sensitivity = self.analysis_sensitivity
            min_duration = self.analysis_min_duration
            adaptive_enabled = self.analysis_adaptive
            cap = cv2.VideoCapture(source_video)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if fps <= 0 or frames < 2: raise RuntimeError("الفيديو غير صالح أو لا يمكن قراءته.")
            min_frames = max(1, round(min_duration * fps))
            detected, reports = set(), []
            self.log(f"تمت قراءة الفيديو: {width}×{height}، {fps:.2f} إطار/ثانية، {frames} إطار.")
            self.update_progress(title="تحليل المشاهد — Content Detector", detail="البحث عن تغيّرات الصورة في الفيديو", mode="indeterminate")
            manager = SceneManager()
            manager.add_detector(ContentDetector(threshold=sensitivity,
                min_scene_len=FrameTimecode(min_frames, fps=fps)))
            manager.detect_scenes(video=open_video(source_video), show_progress=False)
            scenes = manager.get_scene_list()
            for start, end in scenes[1:]: detected.add(start.get_frames())
            reports.append(f"ContentDetector: {max(0, len(scenes)-1)}")
            self.log(f"انتهى Content Detector: {max(0, len(scenes)-1)} انتقالات أولية.")
            self.update_progress(title="معالجة نتائج الكشف", detail="تنقية نقاط القطع ودمج الانتقالات المتقاربة", mode="indeterminate")
            if adaptive_enabled:
                self.log("المرحلة 2/3: تشغيل الكاشف التكيفي.")
                manager = SceneManager()
                manager.add_detector(AdaptiveDetector(adaptive_threshold=max(1.5, sensitivity / 12),
                    min_scene_len=FrameTimecode(min_frames, fps=fps), window_width=2))
                manager.detect_scenes(video=open_video(source_video), show_progress=False)
                scenes = manager.get_scene_list()
                for start, end in scenes[1:]: detected.add(start.get_frames())
                reports.append(f"AdaptiveDetector: {max(0, len(scenes)-1)}")
                self.log(f"انتهى Adaptive Detector: {max(0, len(scenes)-1)} انتقالات أولية.")
            raw = sorted(x for x in detected if 1 <= x < frames - 1)
            merge_gap = max(1, round(fps * 0.12))
            merged = []
            for frame in raw:
                if not merged or frame - merged[-1] > merge_gap: merged.append(frame)
            cuts = []
            for frame in merged:
                if not cuts or frame - cuts[-1] >= min_frames: cuts.append(frame)
            boundaries = [0] + cuts + [frames]
            rows = []
            for i in range(len(boundaries)-1):
                start, end = boundaries[i]/fps, boundaries[i+1]/fps
                if end > start:
                    rows.append({"number": len(rows)+1, "start": start, "end": end, "duration": end-start})
            self.scenes = rows
            self.log(f"المرحلة 3/3: تم تجهيز {len(rows)} مشهد للتصدير.")
            self.update_progress(100, "اكتمل تحليل الفيديو", f"تم اكتشاف {len(rows)} مشهد")
            summary = f"اكتمل التحليل: {width}×{height} | {fps:.2f} FPS | {len(rows)} مشهد | {len(cuts)} نقطة قطع | {', '.join(reports)}"
            self.root.after(0, lambda: self._analysis_done(summary))
        except Exception as exc:
            self.root.after(0, lambda error=str(exc): self._analysis_error(error))

    def _analysis_done(self, summary):
        for item in self.scene_tree.get_children(): self.scene_tree.delete(item)
        for row in self.scenes:
            self.scene_tree.insert("", "end", values=(row["number"], f'{row["start"]:.3f}', f'{row["end"]:.3f}', f'{row["duration"]:.3f}'))
        self.split_status.set(summary)
        self.export_btn.configure(state="normal" if self.scenes else "disabled")
        self.set_busy(False)
        self.log(summary)

    def _analysis_error(self, error):
        self.set_busy(False, "فشل التحليل.")
        self.update_progress(0, "تعذر إكمال التحليل", error[:220])
        self.log("خطأ أثناء التحليل: " + error)
        messagebox.showerror(APP_NAME, error)

    def export_scenes(self):
        if not self.scenes or not self.source_video: return
        self.export_scenes_snapshot = [dict(row) for row in self.scenes]
        self.export_source_snapshot = self.source_video
        self.export_folder_snapshot = self.clips_output_dir
        self.export_btn.configure(state="disabled")
        self.output_btn.configure(state="disabled")
        self.split_status.set("جارٍ تصدير المقاطع...")
        self.update_progress(0, "بدء تصدير المقاطع", f"0 من {len(self.export_scenes_snapshot)} مقطع — الحفظ في {self.export_folder_snapshot}")
        self.log(f"بدأ التصدير إلى: {self.export_folder_snapshot}")
        threading.Thread(target=self._export_worker, daemon=True).start()

    def _export_worker(self):
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            outdir = self.export_folder_snapshot
            scenes_to_export = self.export_scenes_snapshot
            source_to_export = self.export_source_snapshot
            total = len(scenes_to_export)
            self.log(f"سيتم إنشاء {total} ملف MP4 باستخدام FFmpeg (H.264/AAC).")
            for i, row in enumerate(scenes_to_export):
                filename = f"Clip_{run_id}_{row['number']:04d}.mp4"
                output = os.path.join(outdir, filename)
                cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", source_to_export,
                       "-ss", f"{row['start']:.6f}", "-t", f"{row['duration']:.6f}",
                       "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                       "-movflags", "+faststart", output]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode: raise RuntimeError(result.stderr[-1200:])
                done = i + 1
                percent = round(done / total * 100)
                self.root.after(0, lambda n=done, t=total: self.split_status.set(f"جارٍ حفظ المقطع {n}/{t}..."))
                self.update_progress(percent, "تصدير المقاطع", f"اكتمل {done} من {total} — {filename}")
                self.log(f"تم حفظ {done}/{total}: {filename}")
            self.root.after(0, self._export_done)
        except Exception as exc:
            self.root.after(0, lambda error=str(exc): self._export_error(error))

    def _export_done(self):
        self.split_status.set(f"تم تصدير {len(self.scenes)} مقطع بنجاح.")
        exported_count = len(getattr(self, "export_scenes_snapshot", self.scenes))
        exported_folder = getattr(self, "export_folder_snapshot", self.clips_output_dir)
        self.update_progress(100, "اكتمل التصدير بنجاح", f"تم حفظ {exported_count} مقطع في: {exported_folder}")
        self.log(f"اكتمل التصدير بنجاح: {exported_count} مقطع.")
        self.export_btn.configure(state="normal")
        self.output_btn.configure(state="normal")
        self.refresh_stats()
        self.load_queue()
        messagebox.showinfo(APP_NAME, f"اكتمل تصدير {exported_count} مقطع بنجاح إلى:\n{self.clips_output_dir}")

    def _export_error(self, error):
        self.export_btn.configure(state="normal")
        self.output_btn.configure(state="normal")
        self.split_status.set("حدث خطأ أثناء التصدير.")
        self.update_progress(0, "فشل تصدير المقاطع", error[:220])
        self.log("خطأ أثناء التصدير: " + error)
        messagebox.showerror(APP_NAME, error)

    def get_clips(self):
        folder = self.clips_output_dir
        files = [os.path.join(folder, n) for n in os.listdir(folder)
                 if n.lower().endswith(VIDEO_EXTENSIONS) and os.path.isfile(os.path.join(folder, n))]
        return sorted(files, key=lambda p: natural_key(os.path.basename(p)))

    def count_videos_in(self, folder):
        try:
            return sum(1 for n in os.listdir(folder) if n.lower().endswith(VIDEO_EXTENSIONS)
                       and os.path.isfile(os.path.join(folder, n)))
        except Exception: return 0

    def count_videos(self, name):
        return self.count_videos_in(self.folder(name))

    def refresh_stats(self):
        if hasattr(self, "stats"):
            self.stats.set("   ".join([f"Clips: {self.count_videos_in(self.clips_output_dir)}"] +
                [f"{name}: {self.count_videos(name)}" for name in ("MovingCars", "StoppingCars", "ExcludedCars")]))

    def load_queue(self):
        self.stop_video()
        skipped = set(self.state.get("skipped", []))
        self.queue = [p for p in self.get_clips() if os.path.basename(p) not in skipped]
        self.index = 0
        if not self.queue:
            self.current_video = None
            self.video_canvas.delete("all")
            self.status.set("لا توجد مقاطع جديدة للمراجعة.")
        else:
            self.status.set(f"تم تحميل {len(self.queue)} مقطع.")
            self.play_current()
        self.refresh_stats()
        self.log(f"تم تحميل قائمة الفرز: {len(self.queue)} مقطع جاهز للمراجعة من {self.clips_output_dir}")

    def play_current(self):
        self.stop_video()
        if self.index >= len(self.queue):
            self.current_video = None
            self.status.set("🎉 انتهت جميع المقاطع الموجودة في القائمة.")
            self.video_canvas.delete("all")
            return
        self.current_video = self.queue[self.index]
        self.cap = cv2.VideoCapture(self.current_video)
        if not self.cap.isOpened():
            self.status.set("تعذر فتح هذا الفيديو.")
            return
        self.playing = True
        self.status.set(f"{self.index+1}/{len(self.queue)} — {os.path.basename(self.current_video)}")
        self._next_frame()

    def _next_frame(self):
        if not self.playing or self.cap is None: return
        ok, frame = self.cap.read()
        if not ok:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        if ok:
            self._draw_frame(frame)
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        delay = max(15, int(1000 / fps)) if fps and fps > 0 else 33
        self.frame_job = self.root.after(delay, self._next_frame)

    def _draw_frame(self, frame):
        h, w = frame.shape[:2]
        cw = max(1, self.video_canvas.winfo_width())
        ch = max(1, self.video_canvas.winfo_height())
        scale = min(cw / w, ch / h)
        nw, nh = int(w*scale), int(h*scale)
        frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame)
        self.photo = ImageTk.PhotoImage(image)
        self.video_canvas.delete("all")
        self.video_canvas.create_image(cw//2, ch//2, image=self.photo, anchor="center")

    def show_frame_once(self):
        if self.cap is not None and self.current_video:
            pos = self.cap.get(cv2.CAP_PROP_POS_FRAMES)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, pos-1))
            ok, frame = self.cap.read()
            if ok: self._draw_frame(frame)

    def stop_video(self):
        self.playing = False
        if self.frame_job:
            try: self.root.after_cancel(self.frame_job)
            except Exception: pass
            self.frame_job = None
        if self.cap:
            self.cap.release()
            self.cap = None

    def classify(self, category):
        if not self.current_video or not os.path.isfile(self.current_video):
            return
        source = self.current_video
        filename = os.path.basename(source)
        destination_name = None
        if category == "moving": destination_name = "MovingCars"
        elif category == "stopping": destination_name = "StoppingCars"
        elif category == "skip" and self.exclude_var.get(): destination_name = "ExcludedCars"

        self.stop_video()
        if destination_name:
            dest = os.path.join(self.folder(destination_name), filename)
            if os.path.exists(dest):
                name, ext = os.path.splitext(filename); n = 1
                while os.path.exists(dest):
                    dest = os.path.join(self.folder(destination_name), f"{name}_{n}{ext}"); n += 1
            shutil.move(source, dest)
            self.state["history"].append({"source": dest, "original": source, "category": destination_name})
            msg = f"تم نقل {filename} إلى {destination_name}."
        elif category == "skip":
            if filename not in self.state["skipped"]: self.state["skipped"].append(filename)
            msg = f"تم تجاوز {filename} مؤقتاً."
        self.save_state()
        self.log(msg)
        self.index += 1
        self.refresh_stats()
        if self.index < len(self.queue):
            self.play_current()
            self.status.set(msg + "  |  " + self.status.get())
        else:
            self.current_video = None
            self.video_canvas.delete("all")
            self.status.set(msg + "  |  🎉 انتهت القائمة.")

    def undo(self):
        if not self.state.get("history"):
            messagebox.showinfo(APP_NAME, "لا يوجد تصنيف سابق للتراجع عنه.")
            return
        item = self.state["history"].pop()
        source, original = item["source"], item["original"]
        if not os.path.isfile(source):
            messagebox.showerror(APP_NAME, "تعذر العثور على الملف المصنف.")
            self.state["history"].append(item)
            return
        os.makedirs(os.path.dirname(original), exist_ok=True)
        if os.path.exists(original):
            messagebox.showerror(APP_NAME, "يوجد ملف بالاسم نفسه في مجلد ClipsCars.")
            self.state["history"].append(item)
            return
        shutil.move(source, original)
        self.save_state()
        self.load_queue()
        self.status.set(f"تم التراجع عن تصنيف {os.path.basename(original)}.")
        self.refresh_stats()

    def reset_skipped(self):
        self.state["skipped"] = []
        self.save_state()
        self.load_queue()

    def close(self):
        self.stop_video()
        self.root.destroy()

def main():
    root = tk.Tk()
    CarClipSorter(root)
    root.mainloop()

if __name__ == "__main__":
    main()
