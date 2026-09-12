# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

# Project root
root = Path(SPECPATH).resolve()

# Data files to bundle: (source_path, dest_path_in_bundle)
datas = [
    (str(root / "app" / "templates"), "app/templates"),
    (str(root / "app" / "static"), "app/static"),
]

# If you have a grants.db or other runtime data you want seeded,
# uncomment and adjust:
# datas.append((str(root / "grants.db"), "."))

a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "app",
        "app.main",
        "app.database",
        "app.models",
        "app.templates_config",
        "app.routers.scholars",
        "app.routers.records",
        "app.services.scholars",
        "app.services.departments",
        "app.services.grants",
        "app.services.stats",
        "app.utils.dates",
        "app.core.exceptions",
        "app.core.logging",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "jinja2.ext",
        "sqlalchemy.ext.baked",
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ScholarDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # windowed app - no console window shown
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# The admin utility must retain a console so getpass can safely prompt for a
# password. It intentionally has no templates or database payload.
admin_a = Analysis(
    [str(root / "app" / "admin.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=["app.core.auth", "app.database"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

admin_pyz = PYZ(admin_a.pure, admin_a.zipped_data, cipher=block_cipher)

admin_exe = EXE(
    admin_pyz,
    admin_a.scripts,
    admin_a.binaries,
    admin_a.zipfiles,
    admin_a.datas,
    [],
    name="ScholarDeskAdmin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
