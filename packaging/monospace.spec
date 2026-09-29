# PyInstaller spec for MonoSpace.exe (onedir, windowed). Build with packaging/build.ps1, or:
#   .venv\Scripts\python -m PyInstaller packaging\monospace.spec --noconfirm --distpath dist --workpath build
# Output: dist\MonoSpace\MonoSpace.exe plus dist\MonoSpace\_internal\ (server, app, vendor, Python).
# The claude CLI and Ollama are NOT bundled: they are found on PATH / over HTTP at run time.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent            # noqa: F821 (SPECPATH is set by PyInstaller)
ICON = str(ROOT / "assets" / "monospace.ico")

hidden = (collect_submodules("uvicorn") + collect_submodules("server")
          + ["psutil", "tkinter", "tkinter.filedialog", "tkinter.ttk"])

a = Analysis(
    [str(ROOT / "server" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "app"), "app"),                           # index.html + vendor/ (pdf.js, fonts)
        (str(ROOT / "assets" / "monospace.ico"), "assets"),
        (str(ROOT / "LICENSE"), "."),
    ],
    hiddenimports=hidden,
    excludes=["PIL", "pytest", "httpx", "httpx2", "PyInstaller", "setuptools", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MonoSpace",
    icon=ICON,
    console=False,              # no console window for users; logs go to %LOCALAPPDATA%\MonoSpace\logs
    upx=False,
    version=str(ROOT / "packaging" / "version-info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="MonoSpace", upx=False)
