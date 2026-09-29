# MonoSpace

A study app that turns lecture slides and notes into decks, lessons, flashcards, tests and
games. It runs entirely on your own PC. There is no account, no sign-in and no cloud: your
decks and progress stay in a local database on your computer.

- **Builds decks from your modules.** Slide PDFs with a text layer are read directly, with no AI
  needed. Pasted notes, prose PDFs and picture slides use AI.
- **Study modes:** spaced-repetition review, multiple choice, typed answers, flashcards, a study
  guide, test papers, and an AI teacher you can ask questions.
- **AI is optional:**
  - online, it uses **Claude** through the official Claude Code program (your own Claude plan);
  - offline, or without Claude, it uses **Qwen** running locally through Ollama;
  - with neither, everything except the AI features still works.
- **No API keys.** Nothing is sent anywhere except the AI requests you make.
- **Offline-first.** After the first install, it works with Wi-Fi off.

Free and open source (MIT licence).

## Install (Windows 10/11)

You need **Python 3.12** ([python.org](https://www.python.org/downloads/); tick
"Add python.exe to PATH" while installing).

1. **Get MonoSpace.** On GitHub, click **Code → Download ZIP**, unzip it (e.g. to
   `Documents\MonoSpace`), or run `git clone` if you use Git.
2. **Choose where your data lives.** In the MonoSpace folder, copy `.env.example` to `.env`, open
   it in Notepad, and set `DATA_DIR` to a folder **outside** the MonoSpace folder, for example:
   ```
   DATA_DIR=C:\Users\<you>\MonoSpaceData
   ```
   Create that folder. Your database, backups and module PDFs go there.
3. **Start it.** Double-click `start.bat`. The first start needs internet once, to install the
   Python packages. After that it opens MonoSpace in your browser at `http://localhost:8765`.

That's it: you can build decks from slide PDFs and study.

### Optional: offline AI with Qwen
Qwen needs a graphics card with about 8 GB of memory, and a download of about 6.6 GB.
1. Install [Ollama](https://ollama.com/download).
2. In a terminal, run `ollama pull qwen3.5:9b`.
3. Restart `start.bat`. `.env` has the settings (`OLLAMA_MODEL`, `OLLAMA_NUM_CTX`). Keep
   `OLLAMA_NUM_CTX=8192` on an 8 GB card; raise it only if `ollama ps` still shows 100% GPU.

### Optional: Claude when online
1. Install [Claude Code](https://claude.com/claude-code) and sign in with your own Claude plan.
2. Make sure `CLAUDE_CLI=on` in `.env`.

MonoSpace then sends AI requests to Claude whenever you're online, and to Qwen when you're not.
It runs the official `claude` program. It never uses an API key and never reads your login.

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
| `docs/` | Architecture, API, offline AI |

Run the tests:
- `npm test`
- `.venv\Scripts\python -m pip install -r requirements-dev.txt`, then `.venv\Scripts\python -m pytest`

## Licence
MIT. See [LICENSE](LICENSE).
