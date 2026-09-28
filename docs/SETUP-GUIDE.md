# SETUP GUIDE — step by step

About 1–2 hours for Parts 1–6. Part 7 (building the local app with Claude Code) happens
over several sessions, one phase at a time.

Where a step says **Check**, don't move on until it passes.

---

## Part 1 — Install the tools (≈30 min)

Open **PowerShell** (Start → type "PowerShell"). Install whatever the check says is missing.

| Tool | Install | Check (in a *new* PowerShell window) |
|---|---|---|
| Git | `winget install Git.Git` | `git --version` |
| Python 3.12 | `winget install Python.Python.3.12` | `python --version` |
| Node.js LTS | `winget install OpenJS.NodeJS.LTS` | `node --version` |
| Ollama | `winget install Ollama.Ollama` | `ollama --version` |
| Claude Code (the program) | `irm https://claude.ai/install.ps1 \| iex` | `claude --version` |

Why Claude Code again, when you have the VS Code extension? The local app needs the
`claude` **command** to exist, so it can ask Claude questions when you're online.

**If `claude --version` says "not recognized":** the installer sometimes doesn't add itself
to PATH. Run this once, then open a new PowerShell:
```
setx PATH "$env:PATH;$env:USERPROFILE\.local\bin"
```
Then run `claude` once on its own and sign in with your Claude account.

**Check:** all five commands print a version number.

---

## Part 2 — Qwen (≈15 min, mostly download)

1. Memory settings for your 8 GB RTX (run once):
   ```
   setx OLLAMA_FLASH_ATTENTION 1
   setx OLLAMA_KV_CACHE_TYPE q8_0
   ```
2. Restart Ollama: right-click the llama icon in the system tray → **Quit**, then open
   Ollama again from the Start menu.
3. Download the model (~6 GB):
   ```
   ollama pull qwen3.5:9b
   ```
4. Test it:
   ```
   ollama run qwen3.5:9b "Reply with the word ready"
   ```
5. While it's still loaded, run:
   ```
   ollama ps
   ```

**Check:** it replied "ready", and `ollama ps` shows **100% GPU**. If it shows any CPU
share, it's running on the wrong graphics chip — open **NVIDIA Control Panel → Manage 3D
settings → Program Settings**, add `ollama.exe`, and choose the NVIDIA processor.

---

## Part 3 — Your data folder in OneDrive (2 min)

```
mkdir "$env:USERPROFILE\OneDrive\DrillData\import"
mkdir "$env:USERPROFILE\OneDrive\DrillData\modules"
mkdir "$env:USERPROFILE\OneDrive\DrillData\backups"
```

**Check:** File Explorer → OneDrive → `DrillData` with three folders inside.

Copy your module PDFs (IA Modules 1–3, SE modules, …) into `DrillData\modules`.

---

## Part 4 — Export everything from Drill (≈15 min)

Do this in **Claude.ai**, for **every** Drill card you've used in the study-app chat —
each card has its own storage. Start with the **newest** card (its backup also carries
your settings and any unfinished Test paper).

For each card:
1. Open the card → pick any deck → **Manage** tab → **Download a backup** → **Copy**.
2. Open **Notepad** → paste.
3. **File → Save as**:
   - Folder: `OneDrive\DrillData\import`
   - File name: `drill-backup-01.json` (then 02, 03, … for the next cards)
   - Save as type: **All files**
   - Encoding: **UTF-8**

**Check:** one file per card in `DrillData\import`, each several KB or more. Keep the
Claude.ai cards as they are — they're your second copy until the local app is proven.

---

## Part 5 — Put the kit in your repo (≈10 min)

1. Unzip `study-app-starter.zip` into your **Study App** folder, so `CLAUDE.md` sits
   directly inside `Study App` (not inside a sub-folder).
2. In VS Code: **File → Open Folder → Study App**. Open the terminal:
   **Terminal → New Terminal**.
3. Link it to GitHub:
   ```
   git init
   git branch -M main
   git remote add origin https://github.com/YangElisha/Personal-Study-App.git
   git add .
   git status
   ```
4. **Read the list `git status` prints.** It must NOT contain any `.pdf`, `.db`, `.env`,
   or backup `.json` from DrillData. (It will contain `tests/fixtures/*.json` — those are
   meant to be there.)
5. Commit and push:
   ```
   git commit -m "Starter kit: plan, agents, frozen legacy app, reader tests"
   git push -u origin main
   ```
   A browser window opens to sign in to GitHub the first time.

**Check:** refresh `github.com/YangElisha/Personal-Study-App` — you see `CLAUDE.md`,
`docs`, `.claude`, `legacy`, `tests`.

---

## Part 6 — Your settings file (2 min)

1. In VS Code's Explorer, right-click `.env.example` → **Copy**, then **Paste**, and rename
   the copy to `.env`.
2. Open `.env` and check `DATA_DIR` matches your OneDrive path. If your OneDrive folder is
   named differently (e.g. `OneDrive - DLSU-D`), fix it here.

**Check:** `git status` does **not** list `.env`.

---

## Part 7 — Build the local app with Claude Code (one phase per session)

Open the **Claude Code** panel in VS Code. For each phase, paste the prompt, let it work,
approve its edits, and read what it reports. Don't skip the reviewer step.

**Phase 1 — Inventory your data**
> Read CLAUDE.md, docs/PLAN.md and docs/DATA-MIGRATION.md. Use the migration-guardian
> subagent to do Phase 1: read every backup in DATA_DIR\import and write INVENTORY.md.
> Don't import anything yet.

→ Open `DrillData\import\INVENTORY.md`. Is every deck you care about listed? If one is
missing, back up the card that has it (Part 4) and run Phase 1 again.

**Phase 2 — Safety net**
> Use the reader-qa subagent to do Phase 2 of docs/PLAN.md. Show me the test output,
> including the deliberate-failure check.

**Phase 3 — Database**
> Use the backend-builder subagent for Phase 3 of docs/PLAN.md, then migration-guardian to
> import and verify. Show me the full verification table.

→ Every row must match. If anything doesn't, stop there.

**Phase 4 — Run it locally**
> Use the frontend-porter subagent for Phase 4 of docs/PLAN.md.

→ Double-click `start.bat`. Turn Wi-Fi off. Open a deck and study a few cards.

**Phase 5 — AI**
> Use the ai-router subagent for Phase 5 of docs/PLAN.md.

**Phase 6 — Module library**
> Use backend-builder for Phase 6 of docs/PLAN.md.

**After every phase:**
> Use the reviewer subagent on this phase.

When it says **READY TO COMMIT**:
```
git add .
git status
git commit -m "Phase N: <what it did>"
git push
```

---

## Part 8 — Everyday use (once built)

- **Start:** double-click `start.bat` in the Study App folder.
- **Offline:** just use it. The badge shows **Qwen** instead of **Claude**.
- **New module:** drop the PDF into the app as before. It's saved to `DrillData\modules`
  and listed in `MODULES.md`.
- **Backups:** automatic, in `DrillData\backups` (newest 30). OneDrive copies them to the cloud.
- **Only one PC at a time** — don't run the app on two computers at once.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `claude` not recognized | Part 1, the PATH line, then a new PowerShell |
| `ollama ps` shows CPU | NVIDIA Control Panel → set `ollama.exe` to the NVIDIA GPU; or lower `OLLAMA_NUM_CTX` in `.env` |
| Qwen replies are very slow | Same as above — it's overflowing out of the graphics card |
| `git push` rejected: file too large | A PDF got into the repo. Stop and ask Claude Code to remove it from the commit — don't force-push |
| A deck is missing after import | Check INVENTORY.md; the card that has it wasn't backed up yet |
| Claude answers stop working | Anthropic may have changed its rules. Set `CLAUDE_CLI=off` in `.env`; everything runs on Qwen |
