"""Phase 1 preview window: import a channel and work with the paginated, selectable library.
(The full sidebar / dashboard / downloads UI arrives in later phases.)"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from app.channel_parser import InvalidChannelURL, normalize_channel_url
from app.video_manager import VideoManager, format_duration
from app.workers import ImportWorker
from ui.styles import build_qss
from ui.video_list import VideoListModel, VideoRowDelegate, make_video_view

SORTS = [("Date", "date"), ("Title", "title"), ("Duration", "duration")]
FILTERS = [("All Videos", "all"), ("Downloaded", "downloaded"), ("Not Downloaded", "not_downloaded"),
           ("Failed", "failed"), ("Available", "available"), ("Unavailable", "unavailable")]


class MainWindow(QMainWindow):
    def __init__(self, db, settings, thumbs):
        super().__init__()
        self.db, self.settings, self.thumbs = db, settings, thumbs
        self.worker = None
        self.setWindowTitle("YouTube Downloader Studio")
        self.resize(1180, 780)
        self.manager = VideoManager(db, settings.get("page_size"))
        self.model = VideoListModel(self.manager)
        theme, accent = settings.get("theme"), settings.get("accent")
        self.delegate = VideoRowDelegate(thumbs, theme, accent)
        self.view = make_video_view(self.model, self.delegate)
        thumbs.thumbnailReady.connect(self.model.thumbnail_ready)
        self.model.selectionChanged.connect(self._update_labels)
        self._build_ui()
        self._build_shortcuts()
        self.setStyleSheet(build_qss(theme, accent))
        self._reload_channels(settings.get("last_channel_id"))

    # ---- UI ------------------------------------------------------------------
    def _build_ui(self):
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        title = QLabel("Video Library")
        title.setObjectName("title")
        lay.addWidget(title)

        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Channel URL or @handle  (e.g. https://www.youtube.com/@name)")
        self.url_edit.returnPressed.connect(self.start_import)
        self.import_btn = QPushButton("Import Channel")
        self.import_btn.setObjectName("primary")
        self.import_btn.clicked.connect(self.start_import)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(lambda: self.worker and self.worker.cancel())
        clear = QPushButton("Clear")
        clear.clicked.connect(self.url_edit.clear)
        for w in (self.url_edit, self.import_btn, self.cancel_btn, clear):
            row.addWidget(w, 1 if w is self.url_edit else 0)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        lay.addWidget(self.status)
        lay.addWidget(self.progress)

        tools = QHBoxLayout()
        self.channel_box = QComboBox()
        self.channel_box.currentIndexChanged.connect(self._channel_changed)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title or video ID…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search_changed)
        self.sort_box = QComboBox()
        for label, key in SORTS:
            self.sort_box.addItem(f"Sort: {label}", key)
        self.order_btn = QPushButton("Descending")
        self.order_btn.clicked.connect(self._toggle_order)
        self.filter_box = QComboBox()
        for label, key in FILTERS:
            self.filter_box.addItem(label, key)
        self.sort_box.currentIndexChanged.connect(self._sort_changed)
        self.filter_box.currentIndexChanged.connect(self._filter_changed)
        tools.addWidget(self.channel_box, 2)
        tools.addWidget(self.search, 3)
        tools.addWidget(self.sort_box)
        tools.addWidget(self.order_btn)
        tools.addWidget(self.filter_box)
        lay.addLayout(tools)

        lay.addWidget(self.view, 1)

        bar = QFrame()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        self.sel_label = QLabel("")
        self.sel_label.setObjectName("muted")
        bl.addWidget(self.sel_label, 1)
        for text, fn in (("Select Current Page", lambda: self._act(self.manager.select_current_page, True)),
                         ("Select Entire Channel", lambda: self._act(self.manager.select_entire_channel)),
                         ("Select All Matching", lambda: self._act(self.manager.select_matching)),
                         ("Deselect All", lambda: self._act(self.manager.deselect_all))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bl.addWidget(b)
        lay.addWidget(bar)

        pager = QHBoxLayout()
        self.prev_btn, self.next_btn = QPushButton("◀ Previous"), QPushButton("Next ▶")
        self.prev_btn.clicked.connect(lambda: self._page(-1))
        self.next_btn.clicked.connect(lambda: self._page(1))
        self.page_label = QLabel("")
        self.page_label.setAlignment(Qt.AlignCenter)
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.page_label, 1)
        pager.addWidget(self.next_btn)
        lay.addLayout(pager)
        self.setCentralWidget(root)

    def _build_shortcuts(self):
        def add(seq, fn):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(fn)
            self.addAction(a)
        add("Ctrl+I", self.url_edit.setFocus)          # Ctrl maps to Command on macOS
        add("Ctrl+F", self.search.setFocus)
        add("Ctrl+D", lambda: self._act(self.manager.deselect_all))

    # ---- actions -------------------------------------------------------------
    def _act(self, fn, *args):
        fn(*args)
        self.model.reload()
        self._update_labels()

    def _page(self, delta):
        self.manager.goto(self.manager.page + delta)
        self.model.reload()
        self.view.scrollToTop()
        self._update_labels()

    def refresh(self):
        self.model.reload()
        self._update_labels()

    def _reload_channels(self, select_id=None):
        self.channel_box.blockSignals(True)
        self.channel_box.clear()
        self.channel_box.addItem("All channels", "")
        for ch in self.db.list_channels():
            self.channel_box.addItem(f"{ch['title']}  ({ch['video_count']})", ch["channel_id"])
        idx = self.channel_box.findData(select_id) if select_id else 0
        self.channel_box.setCurrentIndex(max(idx, 0))
        self.channel_box.blockSignals(False)
        self._channel_changed()

    def _channel_changed(self):
        cid = self.channel_box.currentData() or None
        self.manager.set_channel(cid)
        self.settings.set("last_channel_id", cid or "")
        self.refresh()

    def _search_changed(self, text):
        self.manager.set_search(text)
        self.refresh()

    def _sort_changed(self):
        self.manager.set_sort(self.sort_box.currentData())
        self.refresh()

    def _toggle_order(self):
        self.manager.set_sort(self.manager.sort, not self.manager.descending)
        self.order_btn.setText("Descending" if self.manager.descending else "Ascending")
        self.refresh()

    def _filter_changed(self):
        self.manager.set_filter(self.filter_box.currentData())
        self.refresh()

    def _update_labels(self):
        total, pages = self.manager.total(), self.manager.total_pages()
        self.page_label.setText(f"Page {self.manager.page + 1} of {pages}   •   {total:,} videos")
        self.prev_btn.setEnabled(self.manager.page > 0)
        self.next_btn.setEnabled(self.manager.page < pages - 1)
        s = self.manager.summary()
        self.sel_label.setText(f"Selected: {s['selected']:,}   •   On this page: {s['on_page']}   •   "
                               f"Total duration: {s['duration_text']}")

    # ---- import ----------------------------------------------------------------
    def start_import(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            normalize_channel_url(self.url_edit.text())
        except InvalidChannelURL as exc:
            QMessageBox.warning(self, "Invalid channel link", str(exc))
            return
        self.import_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress.setVisible(True)
        self.status.setText("Contacting YouTube…")
        self.worker = ImportWorker(self.url_edit.text(), self.db, parent=self)
        self.worker.progress.connect(lambda n: self.status.setText(f"Found {n:,} videos…"))
        self.worker.imported.connect(self._import_done)
        self.worker.failed.connect(lambda m: self._import_end(f"Import failed: {m}", True))
        self.worker.cancelled.connect(lambda: self._import_end("Import cancelled.", False))
        self.worker.start()

    def _import_done(self, channel_id, title, saved, skipped):
        note = f" ({skipped} non-video entries skipped)" if skipped else ""
        self._import_end(f"Imported “{title}”: {saved:,} videos{note}.", False)
        self._reload_channels(channel_id)

    def _import_end(self, message, is_error):
        self.status.setText(message)
        self.import_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress.setVisible(False)
        if is_error:
            QMessageBox.warning(self, "Import", message)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        self.thumbs.shutdown()
        super().closeEvent(event)
