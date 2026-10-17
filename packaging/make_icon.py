"""Render the checked-in SVG to a multi-resolution Windows icon."""
from pathlib import Path
import struct
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
root = Path(__file__).resolve().parent.parent
renderer = QSvgRenderer(str(root / 'assets/dashgo.svg'))
frames = []
for size in (16, 24, 32, 48, 64, 128, 256):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, 'PNG')
    frames.append((size, bytes(data)))
offset = 6 + 16 * len(frames)
header = struct.pack('<HHH', 0, 1, len(frames))
for size, data in frames:
    header += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
    offset += len(data)
(root / 'assets/dashgo.ico').write_bytes(header + b''.join(data for _, data in frames))
