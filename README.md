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

### New in 2.0

- **Teach it back.** The roles swap: an AI plays a student who asks about your deck, and *you*
  explain. It probes ("but why?", "give me an example"), never hands you the answer, and at the end
  marks each concept — *explained fully / surface level / could not explain it / got it wrong* —
  against your deck's own definitions, with the gap in plain words. Then pin the gaps or drill them.
  Talk instead of typing with Windows' own **Win+H** or **Voice Access**; no setup, works offline.
- **Books on a shelf.** Group subjects into books ("Freshman Year · Sem 1"). A spine opens its book;
  finishing one takes its terms out of *to review* without deleting anything.
- **The pinboard.** Sticky notes on every screen, with quiz and exam dates that count down
  ("Quiz · in 2 days"). Review puts a subject with a quiz coming first. Notes can float over the app.
- **Your own order.** Drag a notebook onto another to put it first, second or last; drag it onto a
  subject to move it there. Everything glides, and the page stays where you were.
- **Bookmark ribbons.** A ribbon down each notebook's spine, hanging further the more of that deck
  you know for the long term.
- **A study calendar** on Home: six months of squares filling in on the days you study, with your
  current streak.
- **Written for students.** Settings and Backups in plain words, no "due", a Back button
  (Alt+← and your mouse's back button), and small touches: correct answers get stamped, starting a
  session lays the page down like a notebook opening.

Free and open source (MIT licence).

## Install (Windows 10/11)

Download from the [GitHub Releases](../../releases) page. Choose one:

- **`MonoSpace-Setup.exe`** (recommended). Run it. It installs for your Windows account only
  (no administrator needed) into `%LOCALAPPDATA%\Programs\MonoSpace`, adds a Start menu entry and,
  if you tick it, a desktop icon. Uninstall it from **Settings → Apps**. Uninstalling removes the
  program only, never your data folder or your settings.
- **`MonoSpace-<version>-portable.zip`**. Unzip it anywhere (e.g. `Documents\MonoSpace`) and
  double-click `MonoSpace.exe`. Nothing is installed; delete the folder to remove it.

**"Windows protected your PC".** Windows shows this for programs that aren't code-signed, and
MonoSpace isn't: a signing certificate costs a few hundred dollars a year, and this is a free
project. Click **More info → Run anyway**. To check your download is the real one, compare its
SHA-256 (in PowerShell: `Get-FileHash MonoSpace-Setup.exe`) with the `sha256` in
`MonoSpace-Setup.json` on the same release page.

**Updating.** MonoSpace checks this repo for a newer release when you're online, at most every six
hours, and shows **Update ready**. Tap it to read what's new, then **Update now**: it downloads the
installer, checks it against the release's checksum, takes a snapshot of your database and reopens
itself. Your decks and progress are never touched. You can turn the check off in **Settings → About**.
Copies installed before 2.0 don't know where to look, so install 2.0 by hand once — after that it
updates itself.

**First start.** MonoSpace asks where to keep your data, suggesting `%USERPROFILE%\MonoSpaceData`.
Click **Change…** to pick another folder, then **Start**. Your database, backups and module PDFs go
there. A folder on this PC is safest. If you put it in OneDrive or another synced folder, set it to
**Always keep on this device**, and don't run MonoSpace on two PCs from the same folder at once. A
database that's being synced while it's open can be damaged. MonoSpace's automatic snapshots let you
recover, but it's better not to need them. The choice is saved in
`%APPDATA%\MonoSpace\settings.env`, which has the same settings as the developer `.env` (open it in
Notepad to change them, then restart MonoSpace).

MonoSpace opens full screen in its own window (**F11** leaves full screen and goes back in). Closing it stops MonoSpace (it asks first if a deck is still
being built). Starting it again while it's open brings the open window to the front. New versions
are announced inside the app (see [Updates](docs/RELEASING.md)). You need Microsoft Edge (built into Windows);
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

#### Every part, and how to install it

Only the first three are needed to run MonoSpace. Each row's **Check** should print a version;
run checks in a *new* PowerShell window, so it picks up anything just added to PATH.

| Part | What it's for | Install | Check |
|---|---|---|---|
| **Python 3.12** | Runs the local server | `winget install Python.Python.3.12` | `python --version` |
| **The packages** | FastAPI, uvicorn, the desktop window | in the MonoSpace folder: `python -m venv .venv` then `.venv\Scripts\python -m pip install -r requirements.txt` | `.venv\Scripts\python -c "import fastapi, webview"` |
| **`.env`** | Says where your data lives | copy `.env.example` to `.env`, set `DATA_DIR` to a folder outside this one, and create that folder | `start.bat` opens the app |
| **Git** *(optional)* | Getting the code and updates | `winget install Git.Git` | `git --version` |
| **Ollama + Qwen** *(to build decks offline)* | The local AI that reads your modules | `winget install Ollama.Ollama`, then `ollama pull qwen3.5:9b` (6.6 GB) | `ollama list` |
| **Claude Code** *(optional)* | The online AI, through your own sign-in | `irm https://claude.ai/install.ps1 \| iex`, then run `claude` once and sign in | `claude --version` |
| **Node.js LTS** *(developers)* | `npm test` and `npm run smoke` | `winget install OpenJS.NodeJS.LTS` | `node --version` |
| **Dev packages** *(developers)* | pytest, and the Windows build | `.venv\Scripts\python -m pip install -r requirements-dev.txt` | `.venv\Scripts\python -m pytest -q` |

**Not needed, ever:** an API key of any kind, an account, or a speech engine. Talking is done by
Windows' own voice typing (**Win+H**) and **Voice Access**, which type into whatever box has the
focus — including MonoSpace's — and work offline with nothing installed.

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
- `npm test` (the page parses; the slide reader against its golden files), `npm run smoke` (every screen
  in a real browser on a temporary data folder, no AI), `.venv\Scripts\python -m pytest` (the server).

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
