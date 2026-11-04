# -*- mode: python ; coding: utf-8 -*-
# Gera dist/StockPilot/ (pasta com StockPilot.exe). Uso: pyinstaller stockpilot.spec --noconfirm
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hidden = (collect_submodules("stockpilot") + collect_submodules("sqlalchemy.dialects.sqlite")
          + ["PySide6.QtSvg", "reportlab.pdfbase._fontdata", "openpyxl.cell._writer"])
datas = [("assets/icon.png", "assets"), ("assets/icon.ico", "assets")] + collect_data_files("reportlab")

# Módulos do Qt que o produto não usa: reduz bastante o tamanho do instalador
excludes = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
            "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtBluetooth", "PySide6.QtSensors", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "tkinter", "pytest"]

a = Analysis(["run_stockpilot.py"], pathex=["src"], binaries=[], datas=datas, hiddenimports=hidden,
             hookspath=[], runtime_hooks=[], excludes=excludes, cipher=block_cipher, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="StockPilot", debug=False, strip=False, upx=False,
          console=False, icon="assets/icon.ico" if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="StockPilot")
