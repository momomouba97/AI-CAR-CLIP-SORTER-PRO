"""Vertical video list: Qt Model/View + custom delegate (no per-row widgets, no grid)."""
from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate

from app.database import AVAILABLE
from app.video_manager import format_duration
from ui.styles import palette

ROLE_ROW = Qt.UserRole + 1
ROW_HEIGHT = 84


def _checked(value):
    return value == Qt.Checked or value == 2 or getattr(value, "value", None) == 2


class VideoListModel(QAbstractListModel):
    selectionChanged = Signal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._rows, self._pos = [], {}

    def reload(self):
        self.beginResetModel()
        self._rows = [dict(r) for r in self.manager.rows()]
        self._pos = {r["video_id"]: i for i, r in enumerate(self._rows)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return row["title"]
        if role == Qt.CheckStateRole:
            return Qt.Checked if row["selected"] else Qt.Unchecked
        if role == ROLE_ROW:
            return row
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.isValid() and self._rows[index.row()]["availability"] in AVAILABLE:
            f |= Qt.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        row = self._rows[index.row()]
        want = _checked(value)
        if not self.manager.toggle(row["video_id"], want):
            return False
        row["selected"] = 1 if want else 0
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        self.selectionChanged.emit()
        return True

    def thumbnail_ready(self, video_id):
        i = self._pos.get(video_id)
        if i is not None:
            ix = self.index(i)
            self.dataChanged.emit(ix, ix, [Qt.DecorationRole])


class VideoRowDelegate(QStyledItemDelegate):
    THUMB = QSize(112, 63)

    def __init__(self, thumbs, theme="dark", accent="#E63946", parent=None):
        super().__init__(parent)
        self.thumbs = thumbs
        self.set_theme(theme, accent)

    def set_theme(self, theme, accent):
        self.c = palette(theme, accent)

    @staticmethod
    def checkbox_rect(r):
        return QRect(r.left() + 16, r.center().y() - 10, 20, 20)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, p, option, index):
        row = index.data(ROLE_ROW)
        if not row:
            return
        c = self.c
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        hover = bool(option.state & QStyle.State_MouseOver)
        p.fillRect(r, QColor(c["card_hover"] if hover else c["card"]))
        p.setPen(QPen(QColor(c["border"])))
        p.drawLine(r.left() + 12, r.bottom(), r.right() - 12, r.bottom())

        # checkbox (independent from the thumbnail)
        cb = self.checkbox_rect(r)
        available = row["availability"] in AVAILABLE
        checked = bool(row["selected"])
        p.setPen(QPen(QColor(c["accent"] if checked else c["text2"]), 1.5))
        p.setBrush(QColor(c["accent"]) if checked else Qt.NoBrush)
        p.setOpacity(1.0 if available else 0.35)
        p.drawRoundedRect(cb, 5, 5)
        if checked:
            p.setPen(QPen(QColor("white"), 2))
            p.drawLine(cb.left() + 5, cb.center().y(), cb.left() + 9, cb.bottom() - 5)
            p.drawLine(cb.left() + 9, cb.bottom() - 5, cb.right() - 4, cb.top() + 5)
        p.setOpacity(1.0)

        # thumbnail
        tr = QRect(r.left() + 48, r.top() + (r.height() - self.THUMB.height()) // 2,
                   self.THUMB.width(), self.THUMB.height())
        pm = self.thumbs.get(row["video_id"], row["thumbnail"]) if self.thumbs else None
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(tr.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.setClipRect(tr)
            p.drawPixmap(tr.left() - (scaled.width() - tr.width()) // 2,
                         tr.top() - (scaled.height() - tr.height()) // 2, scaled)
            p.setClipping(False)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["secondary"]))
            p.drawRoundedRect(tr, 6, 6)

        # duration badge
        dur = format_duration(row["duration"])
        fm = QFontMetrics(p.font())
        bw = fm.horizontalAdvance(dur) + 10
        badge = QRect(tr.right() - bw - 4, tr.bottom() - 20, bw, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 190))
        p.drawRoundedRect(badge, 4, 4)
        p.setPen(QColor("white"))
        p.drawText(badge, Qt.AlignCenter, dur)

        # status pill (right side)
        status, color = self._status(row)
        f = p.font()
        pill_w = fm.horizontalAdvance(status) + 20
        pill = QRect(r.right() - pill_w - 16, r.center().y() - 11, pill_w, 22)
        pc = QColor(color)
        pc.setAlpha(40)
        p.setPen(Qt.NoPen)
        p.setBrush(pc)
        p.drawRoundedRect(pill, 11, 11)
        p.setPen(QColor(color))
        p.drawText(pill, Qt.AlignCenter, status)

        # title + meta
        tx = tr.right() + 16
        tw = pill.left() - tx - 16
        bold = p.font()
        bold.setBold(True)
        if bold.pixelSize() > 0:
            bold.setPixelSize(bold.pixelSize() + 1)
        elif bold.pointSizeF() > 0:
            bold.setPointSizeF(bold.pointSizeF() + 1)
        p.setFont(bold)
        p.setPen(QColor(c["text"]))
        title = QFontMetrics(bold).elidedText(row["title"], Qt.ElideRight, max(tw, 40))
        p.drawText(QRect(tx, r.top() + 14, tw, 22), Qt.AlignLeft | Qt.AlignVCenter, title)
        p.setFont(f)
        p.setPen(QColor(c["text2"]))
        meta = f"{row['upload_date'] or 'Date unknown'}   •   {dur}   •   {row['video_id']}"
        p.drawText(QRect(tx, r.top() + 44, tw, 20), Qt.AlignLeft | Qt.AlignVCenter, meta)
        p.restore()

    def _status(self, row):
        c = self.c
        if row["availability"] not in AVAILABLE:
            return row["availability"].replace("_", " ").title(), c["warning"]
        return {"completed": ("Downloaded", c["success"]),
                "failed": ("Failed", c["error"])}.get(row["download_status"], ("Not downloaded", c["text2"]))

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            hit = self.checkbox_rect(option.rect).adjusted(-8, -8, 8, 8)
            if hit.contains(event.position().toPoint()) and index.flags() & Qt.ItemIsUserCheckable:
                new = Qt.Unchecked if _checked(index.data(Qt.CheckStateRole)) else Qt.Checked
                return model.setData(index, new, Qt.CheckStateRole)
        return False


def make_video_view(model, delegate):
    v = QListView()
    v.setModel(model)
    v.setItemDelegate(delegate)
    v.setUniformItemSizes(True)
    v.setMouseTracking(True)
    v.setVerticalScrollMode(QListView.ScrollPerPixel)
    v.setSelectionMode(QListView.NoSelection)
    v.setFrameShape(QListView.NoFrame)
    v.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return v
