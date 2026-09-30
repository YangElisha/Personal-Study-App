# PyInstaller spec for MonoSpace.exe (onedir, windowed). Build with packaging/build.ps1, or:
#   .venv\Scripts\python -m PyInstaller packaging\monospace.spec --noconfirm --distpath dist --workpath build
# Output: dist\MonoSpace\MonoSpace.exe plus dist\MonoSpace\_internal\ (server, app, vendor, Python).
# The claude CLI and Ollama are NOT bundled: they are found on PATH / over HTTP at run time.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent            # noqa: F821 (SPECPATH is set by PyInstaller)
ICON = str(ROOT / "assets" / "monospace.ico")

hidden = (collect_submodules("uvicorn") + collect_submodules("server")
          + ["psutil", "tkinter", "tkinter.filedialog", "tkinter.ttk"])
# The native window: pywebview + pythonnet (WebView2 via WinForms).
wv_datas, wv_bins, wv_hidden = collect_all("webview")
hidden += wv_hidden + ["clr", "clr_loader", "pythonnet"]

a = Analysis(
    [str(ROOT / "server" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "app"), "app"),                           # index.html + vendor/ (pdf.js, fonts)
        (str(ROOT / "assets" / "monospace.ico"), "assets"),
        (str(ROOT / "LICENSE"), "."),
    ] + wv_datas
      # the build stamp (packaging/build.ps1) — how the app knows an update is newer
      + ([(str(ROOT / "packaging" / "build-info.json"), ".")]
         if (ROOT / "packaging" / "build-info.json").is_file() else []),
    binaries=wv_bins,
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
