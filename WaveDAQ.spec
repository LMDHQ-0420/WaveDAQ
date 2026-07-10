# -*- mode: python ; coding: utf-8 -*-
import sys

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('logo.png', '.'),
        ('UI.png', '.'),
    ],
    hiddenimports=[
        'PySide6.QtSvg',
        'PySide6.QtXml',
        'PySide6.QtPrintSupport',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_icon = 'logo.icns' if sys.platform == 'darwin' else 'logo.ico'

if sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='WaveDAQ',
        debug=False,
        strip=False,
        upx=True,
        console=False,
        icon=_icon,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        name='WaveDAQ',
    )
    app = BUNDLE(
        coll,
        name='WaveDAQ.app',
        icon='logo.icns',
        bundle_identifier='com.lmdhq.wavedaq',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': '1.0.0',
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='WaveDAQ',
        debug=False,
        strip=False,
        upx=True,
        console=False,
        icon=_icon,
        onefile=True,
    )
