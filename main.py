
import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox
import cv2
from PIL import Image, ImageTk


APP_NAME = "AI CAR CLIP SORTER PRO"
CATEGORIES = {
    "moving": "MovingCars",
    "stopped": "StoppingCars",
    "excluded": "ExcludedCars",
}

VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".m4v")


class CarClipSorter:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1150x780")
        self.root.minsize(850, 600)

        self.folder = ""
        self.clips = []
        self.index = 0
        self.cap = None
        self.playing = False
        self.photo = None
        self.undo_stack = []
        self.after_id = None

        self.counts = {key: 0 for key in CATEGORIES}

        self.build_ui()
        self.root.bind("<space>", lambda e: self.toggle_play())
        self.root.bind("<Left>", lambda e: self.previous())
        self.root.bind("<Right>", lambda e: self.next_clip())
        self.root.bind("1", lambda e: self.classify("moving"))
        self.root.bind("2", lambda e: self.classify("stopped"))
        self.root.bind("3", lambda e: self.classify("excluded"))
        self.root.bind("<Control-z>", lambda e: self.undo())

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_ui(self):
        self.root.configure(bg="#151922")

        top = tk.Frame(self.root, bg="#202735", pady=12)
        top.pack(fill="x")

        tk.Label(
            top, text=APP_NAME, font=("Arial", 19, "bold"),
            fg="white", bg="#202735"
        ).pack()

        tk.Button(
            top, text="اختيار مجلد المقاطع",
            command=self.choose_folder,
            bg="#2563eb", fg="white",
            font=("Arial", 12, "bold"), padx=18, pady=8
        ).pack(pady=10)

        self.folder_label = tk.Label(
            top, text="لم يتم اختيار مجلد",
            fg="#b9c4d5", bg="#202735"
        )
        self.folder_label.pack()

        self.video_area = tk.Frame(self.root, bg="#05070a")
        self.video_area.pack(fill="both", expand=True, padx=18, pady=14)

        self.video_label = tk.Label(
            self.video_area, bg="#05070a",
            fg="white", text="اختر مجلد الفيديوهات للبدء",
            font=("Arial", 17)
        )
        self.video_label.pack(fill="both", expand=True)

        self.filename_label = tk.Label(
            self.root, text="",
            fg="white", bg="#151922",
            font=("Arial", 13, "bold")
        )
        self.filename_label.pack(pady=3)

        self.progress = tk.Label(
            self.root, text="0 / 0",
            fg="#aab6c8", bg="#151922",
            font=("Arial", 11)
        )
        self.progress.pack()

        controls = tk.Frame(self.root, bg="#151922")
        controls.pack(pady=12)

        self.make_button(controls, "السابق", self.previous, "#475569")
        self.make_button(controls, "تشغيل / إيقاف", self.toggle_play, "#2563eb")
        self.make_button(controls, "التالي", self.next_clip, "#475569")
        self.make_button(controls, "تراجع", self.undo, "#9333ea")

        categories = tk.Frame(self.root, bg="#151922")
        categories.pack(pady=10)

        self.make_button(
            categories, "1 - سيارة متحركة",
            lambda: self.classify("moving"), "#16a34a"
        )
        self.make_button(
            categories, "2 - سيارة متوقفة",
            lambda: self.classify("stopped"), "#d97706"
        )
        self.make_button(
            categories, "3 - استبعاد",
            lambda: self.classify("excluded"), "#dc2626"
        )

        self.stats = tk.Label(
            self.root, text="",
            fg="#cbd5e1", bg="#151922",
            font=("Arial", 11)
        )
        self.stats.pack(pady=10)

        tk.Label(
            self.root,
            text="اختصارات: Space تشغيل | ← السابق | → التالي | 1 متحركة | 2 متوقفة | 3 استبعاد | Ctrl+Z تراجع",
            fg="#8492a6", bg="#151922",
            font=("Arial", 9)
        ).pack(pady=8)

    def make_button(self, parent, text, command, color):
        tk.Button(
            parent, text=text, command=command,
            bg=color, fg="white",
            activebackground=color,
            activeforeground="white",
            font=("Arial", 11, "bold"),
            padx=13, pady=9,
            relief="flat", cursor="hand2"
        ).pack(side="left", padx=5)

    def choose_folder(self):
        folder = filedialog.askdirectory(title="اختر مجلد ClipsCars")
        if not folder:
            return

        self.folder = folder
        self.folder_label.config(text=folder)

        for category in CATEGORIES.values():
            os.makedirs(os.path.join(folder, category), exist_ok=True)

        self.load_clips()

    def load_clips(self):
        if not self.folder:
            return

        self.stop_video()

        self.clips = sorted([
            name for name in os.listdir(self.folder)
            if name.lower().endswith(VIDEO_EXTENSIONS)
            and os.path.isfile(os.path.join(self.folder, name))
        ])

        self.index = 0
        self.counts = {key: 0 for key in CATEGORIES}
        self.undo_stack.clear()
        self.update_stats()

        if not self.clips:
            self.video_label.config(
                image="", text="لا توجد فيديوهات في هذا المجلد"
            )
            self.filename_label.config(text="")
            self.progress.config(text="0 / 0")
            return

        self.show_clip()

    def show_clip(self):
        self.stop_video()

        if not self.clips:
            return

        self.index = max(0, min(self.index, len(self.clips) - 1))
        filename = self.clips[self.index]
        path = os.path.join(self.folder, filename)

        self.filename_label.config(text=filename)
        self.progress.config(
            text=f"المقطع {self.index + 1} من {len(self.clips)}"
        )

        self.cap = cv2.VideoCapture(path)

        if not self.cap.isOpened():
            self.video_label.config(
                image="", text="تعذر فتح هذا الفيديو"
            )
            return

        self.playing = True
        self.play_frame()

    def play_frame(self):
        if not self.playing or self.cap is None:
            return

        ok, frame = self.cap.read()

        if not ok:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()

        if ok:
            area_w = max(400, self.video_area.winfo_width())
            area_h = max(250, self.video_area.winfo_height())

            h, w = frame.shape[:2]
            scale = min(area_w / w, area_h / h)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))

            frame = cv2.resize(frame, (new_w, new_h))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            image = Image.fromarray(frame)
            self.photo = ImageTk.PhotoImage(image=image)
            self.video_label.config(image=self.photo, text="")

        fps = self.cap.get(cv2.CAP_PROP_FPS)
        delay = int(1000 / fps) if fps and fps > 1 else 33
        self.after_id = self.root.after(delay, self.play_frame)

    def stop_video(self):
        self.playing = False

        if self.after_id:
            try:
                self.root.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None

        if self.cap:
            self.cap.release()
            self.cap = None

    def toggle_play(self):
        if not self.clips:
            return

        if self.playing:
            self.stop_video()
        else:
            self.show_clip()

    def next_clip(self):
        if self.index < len(self.clips) - 1:
            self.index += 1
            self.show_clip()

    def previous(self):
        if self.index > 0:
            self.index -= 1
            self.show_clip()

    def classify(self, category):
        if not self.clips or not self.folder:
            return

        filename = self.clips[self.index]
        source = os.path.join(self.folder, filename)
        destination_folder = os.path.join(
            self.folder, CATEGORIES[category]
        )
        destination = os.path.join(destination_folder, filename)

        self.stop_video()

        try:
            if os.path.exists(destination):
                messagebox.showerror(
                    "خطأ", "يوجد ملف بنفس الاسم في مجلد التصنيف"
                )
                self.show_clip()
                return

            shutil.move(source, destination)
            self.undo_stack.append((filename, category))
            self.counts[category] += 1
            self.clips.pop(self.index)
            self.update_stats()

            if self.clips:
                if self.index >= len(self.clips):
                    self.index = len(self.clips) - 1
                self.show_clip()
            else:
                self.video_label.config(
                    image="", text="انتهت جميع المقاطع!"
                )
                self.filename_label.config(text="")
                self.progress.config(text="0 / 0")

        except Exception as error:
            messagebox.showerror("خطأ", str(error))

    def undo(self):
        if not self.undo_stack or not self.folder:
            return

        filename, category = self.undo_stack.pop()

        source = os.path.join(
            self.folder, CATEGORIES[category], filename
        )
        destination = os.path.join(self.folder, filename)

        try:
            shutil.move(source, destination)
            self.counts[category] = max(0, self.counts[category] - 1)
            self.clips.append(filename)
            self.clips.sort()
            self.index = self.clips.index(filename)
            self.update_stats()
            self.show_clip()
        except Exception as error:
            messagebox.showerror("خطأ", str(error))

    def update_stats(self):
        self.stats.config(
            text=(
                f"متحركة: {self.counts['moving']}   |   "
                f"متوقفة: {self.counts['stopped']}   |   "
                f"مستبعدة: {self.counts['excluded']}   |   "
                f"متبقية: {len(self.clips)}"
            )
        )

    def close(self):
        self.stop_video()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = CarClipSorter(root)
    root.mainloop()
