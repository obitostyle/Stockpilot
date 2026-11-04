"""Gera assets/icon.png, assets/icon.ico e assets/logo.svg a partir do logotipo oficial (rodar no desenvolvimento; os arquivos gerados vão no repositório)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stockpilot.ui.brand import LOGO_SVG as SVG  # noqa: E402  (fonte única do logotipo)


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    (out / "logo.svg").write_text(SVG, encoding="utf-8")
    img = QImage(256, 256, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(SVG.encode())).render(p, QRectF(0, 0, 256, 256))
    p.end()
    img.save(str(out / "icon.png"))
    from PIL import Image
    Image.open(out / "icon.png").save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok", out)


if __name__ == "__main__":
    main()
