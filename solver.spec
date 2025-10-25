# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['solver.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('images', 'images'),          # include the images folder
        ('metadata.json', '.'),        # include metadata.json in root
    ],
    hiddenimports=[
        'PIL._tkinter_finder',         # ensures Pillow + Tkinter support
        'PIL.Image', 'PIL.ImageTk', 'PIL.ImageSequence'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
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
    console=False,          # Hide console window
    icon=None,              # You can add an .ico later (e.g., 'md_icon.ico')
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='MurderDronesViewer'
)
