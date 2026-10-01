![MonoSpace](assets/cover.png)

# MonoSpace

A study app that turns lecture slides and notes into decks, lessons, flashcards, tests and
games. It runs entirely on your own PC. There is no account, no sign-in and no cloud: your
decks and progress stay in a local database on your computer.

- **Builds decks from your modules with AI.** An AI reads your slides and notes (including slides
  that are pictures), and writes definitions, explanations and questions for every concept.
  **You need an AI connected to build decks**; see [Your AI](#your-ai-needed-to-build-decks).
- **Studying is fully offline and needs no AI.** Once a deck is built, review, multiple choice,
  typed answers, flashcards, the study guide, test papers and games all work with Wi-Fi off. Only
  the extras (*Ask the teacher*, "Explain this properly", fresh questions on repeat misses) use AI.
- **Your choice of AI:** a **local AI on your PC** (recommended: Qwen through Ollama, or any other
  local model), and/or an **online AI** through its own program and your own plan (Claude Code by
  default; Codex or Gemini CLI too). The two back each other up.
- **No API keys.** Nothing is sent anywhere except the AI requests you make, and (when you're
  online) a check for a new MonoSpace release on GitHub, which you can turn off.
- **Updates from inside the app.** When a new release is out you're told once, can read what's new,
  and update with one click. Your decks and progress are never touched.

Free and open source (MIT licence).

## Install (Windows 10/11)

Download from the [GitHub Releases](../../releases) page. Choose one:

- **`MonoSpace-Setup.exe`** (recommended). Run it. It installs for your Windows account only
  (no administrator needed) into `%LOCALAPPDATA%\Programs\MonoSpace`, adds a Start menu entry and,
  if you tick it, a desktop icon. Uninstall it from **Settings → Apps**. Uninstalling removes the
  program only, never your data folder or your settings.
- **`MonoSpace-<version>-portable.zip`**. Unzip it anywhere (e.g. `Documents\MonoSpace`) and
  double-click `MonoSpace.exe`. Nothing is installed; delete the folder to remove it.

**"Windows protected your PC".** MonoSpace isn't code-signed, so SmartScreen may say the
publisher is unknown the first time. Click **More info → Run anyway**.

**First start.** MonoSpace asks where to keep your data, suggesting `%USERPROFILE%\MonoSpaceData`.
Click **Change…** to pick another folder (for example one OneDrive backs up), then **Start**. Your
database, backups and module PDFs go there. The choice is saved in
`%APPDATA%\MonoSpace\settings.env`, which has the same settings as the developer `.env` (open it in
Notepad to change them, then restart MonoSpace).

MonoSpace opens in its own window. Closing the last MonoSpace window stops it. Starting it again
while it's open just opens another window. You need Microsoft Edge (built into Windows);
without it, MonoSpace opens in your default browser. Logs are in `%LOCALAPPDATA%\MonoSpace\logs`.

### From source (developers)
You need **Python 3.12** ([python.org](https://www.python.org/downloads/); tick
"Add python.exe to PATH" while installing).

1. **Get MonoSpace.** Run `git clone`, or on GitHub click **Code → Download ZIP** and unzip it.
2. **Choose where your data lives.** In the MonoSpace folder, copy `.env.example` to `.env`, open
   it in Notepad, and set `DATA_DIR` to a folder **outside** the MonoSpace folder, for example:
   ```
   DATA_DIR=C:\Users\<you>\MonoSpaceData
   ```
   Create that folder.
3. **Start it.** Double-click `start.bat`. The first start needs internet once, to install the
   Python packages. After that it opens MonoSpace in your browser at `http://localhost:8765`.

**Build the downloads yourself:** `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`
builds `MonoSpace.exe` (PyInstaller), then `MonoSpace-Setup.exe` (Inno Setup, installed per-user
with winget if it's missing), then the portable zip, into `dist\`. To try a build without touching
your real settings, set `MONOSPACE_HOME` to a scratch folder first: `settings.env`, the logs and the
window profile then live there, and the suggested data folder is `<MONOSPACE_HOME>\MonoSpaceData`.

### Your AI (needed to build decks)
**Building a deck needs an AI.** It reads your module, picks out the concepts, and writes proper
definitions, explanations and questions. **After that, studying the deck needs no AI and works fully
offline.**

What you get with no AI connected (from a build with every AI switched off, and the slide reader's own
tests, which use no AI):

| Building from… | Without any AI |
|---|---|
| Slide PDFs with real text and a plain layout | A rough deck: the slides' own wording as definitions, no explanations, basic auto-made questions |
| Slide PDFs with a complex layout (two columns, text beside icons) | Fragments of sentences. Not usable (a real module gave 6 fragments for 60 slides) |
| Pasted notes, prose PDFs | One lump of text per passage. Not usable |
| Slides that are pictures | Nothing. The build stops |

MonoSpace warns you before building when no AI is connected.

So connect an AI before you build. **A local AI is recommended.** It runs on your PC with no
account, no usage limits and nothing leaving your computer, and it keeps working offline. An online
AI is optional. It is faster and more thorough, and when both are connected MonoSpace uses the
online one and falls back to the local one.

- **On your PC (recommended):** Qwen through Ollama (the default), any other Ollama model (Gemma,
  Llama, Mistral…), or LM Studio, llama.cpp, Jan or vLLM. A model that reads images (Qwen 3.5,
  Gemma 3…) is needed for picture slides.
- **Online (optional):** Claude Code (the default), OpenAI Codex, Google Gemini CLI, or any other
  command-line AI. Each runs through the company's own program with **your own** sign-in. There are
  no API keys.

The quickest setup:
1. **Local:** install [Ollama](https://ollama.com/download) and run `ollama pull qwen3.5:9b`. It
   needs a graphics card with about 8 GB of memory and a 6.6 GB download.
2. **Online (optional):** install [Claude Code](https://claude.com/claude-code), run `claude` once
   and sign in.

To use another AI, add two or three lines to the settings file (**Settings → AI → Connect a different
AI** opens it), then press **Reload AI settings**. For example:
```
ONLINE_AI=codex
LOCAL_AI=ollama
OLLAMA_MODEL=gemma3:12b
```
Step-by-step instructions for each AI: **[docs/CONNECT-AI.md](docs/CONNECT-AI.md)**.

## Your data
- Everything lives in your `DATA_DIR`: the database `drill.db`, automatic snapshots in `backups\`,
  and your module PDFs in `modules\`. Nothing is ever uploaded.
- **Manage → Download a backup** gives you one portable file at any time. **Restore** merges a
  backup in, and it never deletes anything.
- Snapshots of the database are taken every time MonoSpace starts, and once a day.

## For developers
| Folder | |
|---|---|
| `app/` | The web app (a single HTML file, with pdf.js and fonts in `app/vendor/`) |
| `server/` | The local server: FastAPI + SQLite, the AI router, the module library |
| `tests/` | Reader regression tests (`npm test`) and server tests (`python -m pytest`) |
| `tools/` | Import verification, the secrets check |
| `packaging/` | The Windows build: PyInstaller spec, Inno Setup script, icon, `build.ps1` |
| `assets/` | The MonoSpace icon |
| `docs/` | Architecture, API, offline AI |

Run the tests:
- `npm test`
- `.venv\Scripts\python -m pip install -r requirements-dev.txt`, then `.venv\Scripts\python -m pytest`

## Licence
MIT. See [LICENSE](LICENSE).
