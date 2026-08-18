# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller get-git.spec

a = Analysis(
    ['app/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('assets/get-git.ico', 'assets')],
    hiddenimports=[
        'keyring.backends.Windows',
        'win32ctypes.core',
        'win32ctypes.pywin32',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='get-git-app',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/get-git.ico',
)
