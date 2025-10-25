# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['solver.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('images/*', 'images'),   # include downloaded images
    ],
    hiddenimports=[
        'pyttsx3.drivers', 
        'pyttsx3.drivers.sapi5', 
        'speech_recognition',
        'requests',
        'bs4',
        'PIL'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MurderDronesViewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # change to True for console debugging
    icon=None,      # you can add an icon later, e.g., "icon.ico"
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MurderDronesViewer',
)
