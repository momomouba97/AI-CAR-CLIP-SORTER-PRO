"""Draw resources/logo.png (1024x1024) with Qt. Run: QT_QPA_PLATFORM=offscreen python scripts/make_icon.py"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

app = QGuiApplication([])
S = 1024
img = QImage(S, S, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
g = QLinearGradient(0, 0, S, S)
g.setColorAt(0, QColor("#E63946"))
g.setColorAt(1, QColor("#8B5CF6"))
p.setBrush(QBrush(g))
p.setPen(Qt.NoPen)
p.drawRoundedRect(QRectF(64, 64, S - 128, S - 128), 200, 200)
p.setBrush(QColor("white"))
tri = QPainterPath()
tri.moveTo(QPointF(420, 330)); tri.lineTo(QPointF(420, 560)); tri.lineTo(QPointF(620, 445)); tri.closeSubpath()
p.drawPath(tri)
p.setPen(QPen(QColor("white"), 56, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
p.drawLine(QPointF(512, 650), QPointF(512, 780))
p.drawLine(QPointF(512, 780), QPointF(450, 718))
p.drawLine(QPointF(512, 780), QPointF(574, 718))
p.end()
out = Path(__file__).resolve().parent.parent / "resources" / "logo.png"
out.parent.mkdir(exist_ok=True)
img.save(str(out))
print("wrote", out)
