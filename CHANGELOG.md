# CHANGELOG

Newest first. Every change gets an entry in the same commit.

## [Unreleased]

### Changed — talking is Windows’ job, not ours (redesign 2.0, 2026-10-06)
- The microphone button in "Teach it back" is gone. It used the browser’s speech recognition, which
  streams audio to a service on the internet — and WebView2 wires up no such service, so it never worked.
- Windows already does this better and on-device: **voice typing (Win+H)** and **Voice Access** type into
  whatever box has the focus, this one included, with the Wi-Fi off. The answer box says so, and is a
  plain labelled textarea, which is all dictation needs. No API, no model, no download.


### Added — "Teach it back": you explain, an AI student asks (redesign 2.0, 2026-10-06)
- A new mode on every deck, beside "Teach me". Pick who you are teaching — **curious first-year**,
  **confused classmate** or **tough examiner** — and how many concepts (3/5/8). The concepts you have
  never explained, or explained worst, come first.
- The student asks an opening question, you explain in your own words, and it asks one or two probing
  follow-ups ("but why?", "can you give an example?"). It never explains anything to you and never gives
  the answer away — if you are wrong it asks the question that makes you notice. Three goes per concept,
  or "Next concept" when you are done.
- **Talk instead** of typing where the browser can hear you (its own speech recognition; the button is
  absent when it is not available). Your stickies for that deck sit alongside, and you can pin one
  mid-session.
- **The marking**: every concept gets *Explained it fully / Surface level / Could not explain it / Got it
  wrong*, with the gap in plain words and one thing to say next time — judged **only against the deck’s
  own definitions**, never an invented standard. Then pin every gap to your wall, drill the shaky ones,
  or go again.
- Kept with the deck’s progress (`PROG.explain`, the last 30 sessions), so it travels in a backup.
  If the marking call fails, the conversation stays on screen and can be marked again — nothing said is lost.


### Added — put your notebooks in your own order (redesign 2.0, 2026-10-06)
- Drag a notebook **onto another notebook** to drop it in front of or behind it: the left half of the one
  you hover over puts it first, the right half puts it after, and a line down that edge shows where it
  will land. Dropped on a notebook in another subject, it moves there **and** lands in that spot.
- **Move earlier / Move later** in a notebook’s "..." menu does the same without a mouse.
- Reordering **glides**; only a move to another subject keeps the flying arc. The order is the order of
  `LIB.decks`, which the Library, the Shelf and the sidebar already drew in — no new field is stored.


### Fixed — the colour rows in Appearance (redesign 2.0, 2026-10-06)
- "Every colour, yours" had its rows collapsed on top of each other, with the hex boxes overlapping the
  names. The redesign added a pill on/off switch called `.sw` — the same class name the colour rows have
  used since the start — and it squashed every row to 48×28. The switch is now `button.sw`, and the colour
  rows are scoped to `.swatches .sw` so neither can take over the other again.


### Added — the small touches: a stamp, a page turn, screens that come in (redesign 2.0, 2026-10-06)
- A right answer is **stamped** like a marked paper: "Correct", or "Mastered" when that answer locked the
  concept in. Decoration only — nothing about marking or the ladder changed.
- Starting a session **lays the study screen down like the next page of a notebook**: it swings in from its
  right edge and settles flat. Nothing covers the screen, so it never blanks.
- Every other screen **comes in** (a short rise and fade) instead of snapping.
- All three are off under "reduce motion".


### Added — bookmark ribbons and the study calendar (redesign 2.0, 2026-10-06)
- **Bookmark ribbon**: a silk ribbon sewn into each notebook’s spine, hanging further down the cover the
  more of that deck you know for the long term. None until you master your first concept, full cover at
  100%. Drawn from the mastered count that already feeds the progress bar — nothing new is stored.
- **Your study calendar** on Home: six months of squares, one per day, filling in on the days you study,
  with the month above and "N days in a row" beside the heading. Days you studied before this existed
  are filled in from when each deck was last opened (display only). New key `studydays`.


### Added — the pinboard: notes everywhere, quiz and exam dates, notes that float (redesign 2.0, 2026-10-06)
- A tab on the right edge (with a count, or "N soon" for dates this week) slides out the pinboard on every
  screen. New note: text, Note / Quiz / Exam, a date, attach to the open deck or a subject, colour.
  **Coming up** lists dated notes soonest first with countdowns ("Quiz · in 2 days · Thu, Oct 8"); past
  ones fade. Undated **Notes** can be dragged to reorder. Any note can be **kept on screen**: it floats
  over the app, draggable anywhere (position saved), until "Back to board".
- **Review** puts decks with a quiz or exam in the next three weeks first, labelled "Quiz in 2 days".
- Same stickies as the deck's "Stickies" card and the Home wall (LIB.stickies; new optional fields: date,
  kind, folderId, float).
- docs/FUTURE.md: future features, starting with "Teach it back" (you explain, an AI student asks).


### Changed — Settings and Backups in plain words (redesign 2.0, 2026-10-06)
- Written for students, not developers: "Your AI helper", "While you study", "Give me more on what I
  miss", "Mark spelling strictly", "Tell me when there's a new version"… Every option is kept.
- Backups: "Save a copy" / "Bring a copy back" side by side, level and equal height (a spacing rule had
  pushed the second box down); "Automatic safety copies"; file names and the restore command moved under
  "For advanced users"; "Where your work is kept" without DATA_DIR or server talk.


### Added — books on a shelf; bolder card titles (redesign 2.0, 2026-10-06)
- **Books** hold subjects ("Freshman Year · Sem 1"). The Library opens with a shelf of spines (taller for
  longer names, the count of terms to review at the foot); a spine opens its book — the cover swings open
  and its subjects rise in. Inside: Add subjects, Finish book / Reopen, Rename, Colour, Delete book.
  A subject is filed by dragging its title onto a spine (spines wiggle while you drag) or by ticking it.
  **Finished** books keep everything but their terms leave "to review" (Home, Review, badges) until
  reopened; their spines fade and get a ✓. Deleting a book never deletes subjects. The Shelf sidebar
  groups subjects under their books. Stored additively (LIB.books, folder.bookId).
- **Card titles**: the label that opens a card is now a bold title in ink over a strong rule; what
  follows a dash stays quieter beside it ("Concept board · one square per concept").


### Added — moving a notebook is animated (redesign 2.0, 2026-10-06)
- Dragging lifts the notebook (dimmed, tilted). On drop — or "Move to…" — it flies from its old place
  to its new one with a small arc and lands; the others slide to open or close the gap; the subject
  that receives it lights up in its colour. The page keeps its scroll position instead of jumping to
  the top. Reduced motion: no movement.


### Changed — no "due"; a Back button (redesign 2.0, 2026-10-06)
- Nothing is "due": the student decides when to review. Every place that said "due" now says how
  many terms are ready ("135 terms to review", "32 to review", "To review", "All caught up"), with
  "terms" instead of "concepts". Review page: "Pick a deck to go over the terms ready to review — you
  choose when."
- **Back**: an arrow left of the logo (and Alt+Left, and the mouse's back button) returns to the
  screen you were actually on before — the same deck and tab — not to a fixed page. From a study
  session, game, lesson or test paper it returns to where you started it (a test's draft is saved
  first). Going back to New deck keeps what you typed.


### Changed — the loading screen builds the logo (redesign 2.0, 2026-10-06)
- "M" and the accent cursor appear together (the app icon), the cursor blinks once, then
  "onoSpace" comes out of the cursor — nearest letters first — pushing the M left until it reads
  "MonoSpace▌"; the tagline follows and the cursor keeps blinking. About 2.5 s of animation, shown
  at least 4.8 s; a click or any key skips it. In the colours of the theme used last time (saved
  by Theme.apply), paper colours the first time. Reduced motion: the finished logo, no movement.
  Replaces the dark orb-and-moons canvas animation.

### Changed — the logo (redesign 2.0, 2026-10-06)
- The header logo is now the wordmark and a solid cursor in the theme's accent ("MonoSpace▌"),
  chosen from three mock-ups. It replaces the purple orb image (from the old dark design) and the
  loose underscore that sat apart from the word. Drawn in CSS and sized in em, so it lines up at
  any text size and takes each theme's accent.
- **App icon** (window, taskbar, Start menu, installer, exe): the same idea as a monogram — a cream
  "M" and the accent cursor on a warm near-black tile, drawn as shapes in `packaging/make_icon.py`
  so every size from 16 to 256 px is crisp. The orb artwork stays for the README cover and the
  loading screen.

### Fixed / added — clean-up before going public (2026-10-01)
- **Removed the Claude.ai leftovers**: the hidden "Anthropic API key" card, its storage and its
  buttons (never used since the local port; anything a browser may hold is left alone), and the
  backup text "Inside Claude, use Copy instead".
- **Codex and Gemini checked against their official docs** (not installed): every option used
  exists. Codex now also runs with `--ephemeral` (keeps no session files); Gemini with
  `--output-format text`. docs/CONNECT-AI.md says so, and that Gemini CLI's free tier (personal
  Google sign-in) needs no subscription.
- **Activity logs older than 90 days** are removed at start-up — only files named exactly
  `activity-YYYY-MM-DD.jsonl` in `DATA_DIR\logs`; crash reports and everything else stay.
- **`npm run smoke`** (`tests/smoke.mjs`): MonoSpace on a temporary data folder with every AI off,
  one deck added through the app, then all 34 screens/modes opened in a real browser; fails on any
  page error or "Something went wrong".
- **README**: why Windows warns about an unsigned program and how to check the download's SHA-256;
  a data folder on this PC is safest (in OneDrive: "Always keep on this device", one PC at a time);
  a second start brings the open window forward; new versions are announced in the app.

### Added — new releases announced in the app, with "What's new" (2026-10-01)
- A build made with an update repo (`packaging/update-repo.txt` or `MONOSPACE_UPDATE_REPO`, e.g.
  `YangElisha/MonoSpace`) checks that repo's latest **GitHub Release** when online — at most every
  6 hours, silently when offline or not found. A newer release is announced once ("MonoSpace 1.1 is
  available"), stays as **Update ready** in the sidebar, and opens **What's new** (the release
  notes, Markdown: headings, bullets, bold, italics, code) with **Update now** / **Later**.
  Updating downloads the installer, refuses it unless its sha256 matches the release's
  `MonoSpace-Setup.json`, then installs and reopens exactly like a local update. The project
  folder (dist) is still checked first, so the developer's copy updates from fresh builds.
- **Settings → About**: "Check now", and "Check for new versions online" (on by default; off means
  MonoSpace never goes online by itself for updates).
- `tools/release.py` publishes the build as a release (GitHub CLI, or prints the github.com
  steps); it refuses a build whose installer and record don't match, whose version differs, or
  that wouldn't check the repo it's released to. `docs/RELEASING.md` explains the steps and how to
  write the notes for students.
- Not switched on yet: the repo is private, so builds carry no update repo and no copy contacts
  GitHub. Tested against a stand-in GitHub: offered once, notes shown, Later, not re-announced,
  checks off, offline and missing releases quiet, at most one check per 6 hours, tampered download
  refused, project folder first.

### Added — connect other AIs: Codex, Gemini, any CLI; any Ollama model or OpenAI-compatible local server (2026-10-01)
- **Online AI** (`ONLINE_AI`): `claude` (default; old `CLAUDE_CLI=on` still works), `codex` (OpenAI
  Codex CLI: `codex exec`, empty temp folder, `--sandbox read-only`, pictures as `--image` files,
  answer from `--output-last-message`), `gemini` (Gemini CLI, text only — pictures go to the local
  AI), `custom` (any CLI via `ONLINE_AI_COMMAND` with `{prompt_file}` `{output_file}` `{images}`
  `{workdir}` `{model}`), or `off`. Always the company's own program and the user's own sign-in —
  no API keys. Sign-out and usage-limit handling, pausing and "Try … again" work for each.
- **AI on this PC** (`LOCAL_AI`): `ollama` with any model (`OLLAMA_MODEL`), or `openai` — any
  OpenAI-compatible server (LM Studio, llama.cpp, Jan, vLLM) at `LOCAL_AI_URL`. Thinking is switched
  off (`reasoning_effort: "none"`; a server that rejects it is asked again without): measured on
  Ollama's /v1 with qwen3.5:9b, thinking returned an empty answer; off, a full answer in 3.5 s and a
  slide picture read exactly in 5.2 s. `off` is possible too.
- **Names everywhere**: the app shows the connected AIs' names (badge, Ask the teacher switch,
  replies, activity log, supervisor, Settings, dialogs) instead of "Claude"/"Qwen"; with Claude and
  Qwen nothing changes. Replies carry `ai_name`; `/api/ai/route` gives `cloud_name`, `local_name`,
  `local_ok`, `signin_help`.
- **Settings → AI**: which AIs are connected, "Connect a different AI" with examples, **Open
  settings file** and **Reload AI settings** (`POST /api/ai/reload`, no restart needed).
- **No AI connected?** Building now warns first ("Building a deck needs an AI…"), with "Build a rough
  deck anyway" / Cancel. Checked with every AI off: a two-column module gave 6 fragments, pasted
  notes one lump, a picture module nothing — previously built silently.
- Settings files may have a comment after a value (`ONLINE_AI=codex   # or claude`).
- **docs/CONNECT-AI.md**: step by step for Claude, Codex, Gemini, any CLI, Ollama models, LM Studio,
  llama.cpp, Jan, vLLM; troubleshooting; every setting. **README** rewritten to be straight about it:
  building decks needs an AI (a local one recommended); studying is fully offline with no AI.
- Tests: Codex/Gemini/custom with a stand-in CLI (argv, stdin, image files, answer file vs printed
  noise, sign-out, usage limit), an OpenAI-compatible stand-in server (text, pictures, thinking
  stripped), names, reload, route. Codex and Gemini were not installed here, so their real CLIs are
  untested; if their options change, `ONLINE_AI=custom` takes the working command.

### Fixed — "___" in AI-written questions (2026-10-01)
- Questions the AI wrote itself sometimes contain a blank as three underscores ("usable and ___
  with other systems"). Only four or more were turned into a slot, so these showed as a line.
  Any run of three or more underscores now shows as the blank slot (saved decks included;
  `__init__` and the like are left alone). The teaching pass, "More questions" and the
  supervisor now ask for direct questions instead of fill-in-the-blanks.

### Added — update from inside MonoSpace (2026-10-01)
- Every build is stamped (`build-info.json` inside the program; `dist\MonoSpace-Setup.json`
  beside the installer, with its sha256). When a newer build is in the project's dist folder,
  **Update ready** appears in the sidebar and **Update now** in Settings → About.
- Updating: refuses while a deck is building; checks the installer matches its record (not
  half-copied); copies it out of dist; takes a `pre-update` database snapshot; closes MonoSpace;
  a hidden helper waits for it to exit, installs silently over the old version (the old
  program files are removed first — `[InstallDelete] {app}\_internal`) and opens the new one
  (`/RELAUNCH=1`). The data folder, settings and logs are never touched.
- Tested: the update decision (newer / same / older build, record with a BOM, half-copied
  installer refused) and the hand-off with real processes (the helper outlives MonoSpace, waits
  for it to close, then runs the installer with /VERYSILENT … /RELAUNCH=1).
- The copy installed before this change has no stamp, so it is updated once by hand; every
  update after that is one click.

### Fixed — "Mark as correct" after "Almost — you need the whole term" (2026-10-01)
- A partial answer ("Customized" for "Customized products") now has "I was right — mark as
  correct" too; marking it right means that wording is accepted from then on. No AI check there
  (it would only say "partly right"). The message no longer repeats the term before its
  definition.

### Fixed — Settings layout (2026-10-01)
- "Layout and length" and "Appearance" touched with no gap (a card after the study-options block
  got no spacing). Checked at 780, 1000 and 1100 px wide and at the largest text size: nothing
  runs off the page.
- The AI box no longer says "there is nothing to set here": it says Claude or Qwen, why Qwen is
  answering (Claude Code signed out / usage limit), how to get Claude back, and that Ask the
  teacher has its own Claude/Qwen switch.

### Fixed — seeing the answer through the hint no longer counts as knowing it (2026-10-01)
- Tapping a hidden-term chip twice shows the whole answer. Choosing or typing that answer
  afterwards now counts as not known yet ("You saw the answer — counted as not known yet"), in
  study sessions and in Sprint ("counted as a miss"). One tap (first letter and length) is a hint
  and still counts as right. No "I was right" button or AI check after a full reveal.

### Added — pick Claude or Qwen in Ask the teacher; signed-out Claude handled; every log entry named (2026-10-01)
- **Ask the teacher: Claude | Qwen.** A switch at the top of the chat (Claude each time the app
  opens). Claude: Claude answers, Qwen if Claude can't. Qwen: Qwen answers on this PC and Claude
  is never asked (`"only":"qwen"`). Each reply says who wrote it. Only this chat has the choice.
- **Claude Code signed out.** "Failed to authenticate: OAuth session expired" used to fail
  every request on Claude first (about 20 s each) before Qwen answered, while the log still said
  "AI: claude". Now it pauses Claude for 5 minutes, says so once ("Claude Code is signed out, so
  Qwen is answering"), the badge reads "Claude signed out", and the Activity drawer shows the fix
  (run `claude`, then `/login`) with a **Try Claude again** button (`POST /api/ai/claude/retry`).
- **"forgot", "idk", "no idea", "?"…** are not sent to the AI to check, and get no "I was right".
- **Every AI request is named in the log** — Answer check, Teacher chat, Explain my answer,
  Explain a concept, More questions, Replace a bad question, Read a slide, Read page pictures,
  Outline the module, Teach concepts, Merge duplicates, Supervisor check, Write the study guide,
  Mark an exam, problem-course steps and more; entries saved earlier as "Other" are named from
  their preview. Requests outside a build are grouped as "While studying · …". Requests Qwen
  answered in Claude's place are amber and say why (signed out / paused / failed); red is kept
  for real failures.

### Fixed — fair marking of typed answers; questions never show their own answer; layout (2026-09-30)
- **Typed answers in your own words.** An answer holding every meaningful word of the expected
  one, in any order and with more around it, is right ("Playing games on work laptop" for "game
  playing"). When a typed answer is still marked wrong, the AI checks whether it means the same
  (Claude online, Qwen offline) and counts it right if so; either way "I was right — mark as
  correct" is there. Marking it correct undoes the wrong grade exactly (streak, progress, the
  extra questions queued) and adds your wording to the question's accepted answers.
- **"Which term does this describe?" no longer shows the term.** Questions saved by earlier
  builds carried the plain definition ("Computer misuse is the improper use…"). The answer is
  now hidden whenever a question is shown, so every existing deck is fixed without rebuilding.
  The feedback no longer repeats the term three times.
- **Sidebar.** The "Subjects" heading stays above the list instead of sliding over it while
  scrolling; the AI badge sits in the sidebar under Settings instead of floating over the page.
- `npm test` now also checks that every inline script in app/index.html parses
  (`tests/check-app-syntax.js`) — a syntax error anywhere leaves the app blank, and the reader
  tests only load the reader.

### Fixed — Module 2's garbled terms and the Gospel slide; simpler Activity log; remove while learning (2026-09-30)
- **Garbled term names.** On slides built from two-column boxes, the slide reader ran titles and
  text together, so "terms" came out as whole sentences in Title Case ("Incremental Development
  Benefits the Cost of Accommodating…"). The PDF's own text was fine. Now, when 15% or more of the
  names read are over 8 words (the reader tests never have one), that reading is dropped and the
  page text goes through the outline and teaching pass instead, with running footers left out.
  Module 2 now builds in about a minute: 40 clean terms, each found in the module.
- **Not course content.** Prayers, gospel or bible readings and devotionals are recognised by
  the reader (asked about, like activities), left out of page text ("Left out page 2 — a prayer
  or reading"), skipped by page transcription and by the outline, and caught by "Remove course
  outcomes & admin" on existing decks.
- **Duplicate folding** no longer merges narrower terms into broader ones (it had folded
  "Software validation" and "Software specification"); at most a fifth of a deck is folded.
- **Teach me → "Not needed — remove".** Takes a concept out of the deck while you learn; it is
  kept (with its progress) under Manage → Removed concepts, where "Bring back" restores it.
- **Activity log redesigned.** One line of status, then one card per build (or per Claude check):
  done / stopped / building, time taken, Claude and Qwen requests, real problems only. Open a card
  for its steps; each AI request expands to what was asked and answered; "Copy report for AI" per
  build. Earlier sessions load automatically; the latest crash sits on top with its copy button.
- A single failed reachability check no longer counts as offline for 15 s (3 s now), and the
  supervisor asks twice before skipping its check. Checked on real models: Claude reviewed 11
  concepts Qwen wrote after a usage limit and corrected 5, including the CMM levels in the wrong
  order.

### Added — AI activity log, Claude as supervisor, crash reports; no more ______ (2026-09-30)
- **Hidden terms read naturally.** A definition that opens with its own term ("Software costs
  are the expenses of…") is rephrased to start at what it says ("The expenses of…"); where the
  term appears mid-sentence it becomes a soft chip — tap for a hint (first letter, length), tap
  again to see it. Fill-in-the-blank shows a slot instead of underscores. Only the term itself
  (or its acronym) is hidden now; its words scattered through a sentence stay readable. Stored
  data is unchanged (older "______" questions show as chips too).
- **Cards and Terms fit their text.** The boxes grow with what is in them (no inner
  scrollbars); each flashcard is a tile, term in bold, and looks like text until edited.
- **AI activity log.** The AI badge (bottom left) is now a button: it opens a drawer with every
  AI request (step, Claude/Qwen, fallback reason, seconds, tokens, previews of prompt and
  answer), every build step and every error, filterable (AI requests · Builds · Supervisor ·
  Problems). The badge counts new problems. Kept on this PC in `DATA_DIR\logs` (one file a day);
  "Earlier sessions" loads them. Works offline — it then shows Qwen's work alone.
- **Supervisor.** The teaching pass records who wrote each concept. When Qwen wrote some
  (offline, or Claude failed), Claude checks them against the module before the deck is saved:
  it confirms, corrects (what Qwen wrote is kept in the concept) or flags a doubt. Supervisor
  requests go to Claude only (`"only":"claude"`), never back to Qwen. If Claude isn't there,
  the concepts are marked "written by Qwen, not checked by Claude yet", and the deck's Overview
  offers "Have Claude check them" once it is back. Terms show the status per concept.
  Tested with real models: Qwen built an 8-concept deck offline (97 s); Claude then checked it
  in 13 s and fixed 4 (questions that didn't match their concept, an invented claim).
- **Crash reports.** A build that stops on an error (not one you stopped), or an error nobody
  caught, saves `DATA_DIR\logs\crash-….md`: the error and stack, the steps before it, the AI
  requests (table, problems in detail). "Copy for AI" / "Copy report for AI" puts it on the
  clipboard as Markdown ready to paste into an AI chat.

### Fixed — closing the window no longer loses a build silently; one window only (2026-09-30)
- The desktop window (WebView2) shows no "leave page?" prompt, so closing MonoSpace mid-build
  dropped the build and the whole queue without a word. The page now tells the server how many
  builds are running or queued (`/api/builds`), and the window asks before closing on one
  (Cancel keeps it open). Tested on a real window: warning shown, Cancel kept it, idle close
  immediate.
- Starting MonoSpace while it is already open now brings the open window to the front (restoring
  it if minimised) instead of opening a second one. Seen in the log: a double-click opened two
  windows, and closing the first stopped the server under the second.
- The log names the pywebview version instead of "?".

### Changed — page images read by Sonnet, with figures explained (2026-09-30)
- Compared Haiku and Sonnet on every page of a real picture module against the page images:
  Haiku changed three words in small print ("Infer" → "Uses", "combining" → "constituting",
  "subtasks" → "subsets"); Sonnet made no misreadings and kept the module's own spelling. With thinking
  off, both took 8-15 s a page, so page images go back to Sonnet (the "fast" tier stays
  available, unused).
- Transcription now adds one `[Figure: …]` line for a diagram, chart or picture that teaches
  something (e.g. AI ⊃ ML ⊃ DL; manual feature extraction vs a CNN), instead of only its labels.
- Checked: the same module in 62 s, 14 requests, 22 concepts all taught, names found in the
  source; small print correct; 7 figures explained. Reader tests 3/3.

### Fixed — builds were slow (a 6-page picture PDF: 273 s → 60 s) (2026-09-30)
- Measured per request (the server now logs model, seconds and tokens for every Claude call):
  about 4 s start-up each, and most of the rest was **hidden thinking**: a 4-concept teaching
  request was 7,038 tokens / 66 s at Claude Code's default, 1,809 / 22 s at low effort, with
  nearly the same answer; Haiku spent up to 11,000 tokens / 100 s on one maths-heavy page.
- Every `claude -p` now runs with `--effort low` (`CLAUDE_CLI_EFFORT`; not `CLAUDE_EFFORT`,
  which Claude Code itself sets) and `MAX_THINKING_TOKENS=0`. Faster and far less usage.
- Page images are copied out by **Haiku** (`"tier": "fast"`, `CLAUDE_FAST_MODEL`), 4 pages at
  once; teaching stays on Sonnet.
- Up to 4 Claude requests run side by side (was 2); passages are outlined side by side; teaching
  runs 4 workers of 4 concepts. Qwen stays one at a time.
- Teaching replies are shorter: 1-2 sentence explanations, one-line reasons, extra terms get a
  definition and explanation (their recall questions are made locally).
- Checked on a copy of the real database, the 6-page picture PDF with Claude: 273 s → 241 →
  173 → 165 → **60 s**, 14 requests, 20 concepts all taught, names found in the source.
  221 server tests, reader tests 3/3.

### Fixed — one picture PDF used ~120 Claude requests and a whole usage window (2026-09-29)
- Cause: a 6-page picture PDF went page by page through the exhaustive extract / re-check /
  expand loop, every maths symbol became a concept (267), and each was taught 3 per request;
  Claude Code's default (largest) model answered; after the usage limit every request failed on
  Claude first, then Qwen got a job sized for Claude.
- Picture pages are typed out once and read as one document with the rest of the material.
- Material is **outlined** in large passages (one request each; 14,000 characters for Claude,
  3,500 for Qwen), notation and worked examples grouped, a hard per-passage ceiling, then taught.
  The exhaustive loop (`completeBuild`) is gone, and with it the unused Depth control.
- Teaching: 6 concepts per Claude request sharing one copy of the source; Qwen one per request.
  The model is checked before every request, so a mid-build switch to Qwen is sized for Qwen.
- **Budget:** a build that needs more than 25 AI requests asks first.
- Server: Claude runs **Sonnet** unless `CLAUDE_MODEL` says otherwise; a usage / session / rate
  limit pauses Claude for 30 minutes (`/api/ai/route` says `claude_paused`) so requests go
  straight to Qwen.
- **Accuracy:** a concept's name must be found in the module text (word stems); otherwise it
  keeps its own name, and invented extra terms are dropped. Filler endings ("task type",
  "mechanism", "objective"…) are removed.
- Outline replies of plain names (Qwen sometimes drops "| topic") are used, not discarded; an
  empty reply is retried once; a passage that still yields nothing is kept whole as one concept
  (a Qwen run had lost the whole neural-network passage). Names over 8 words and generic words
  ("algorithms", "programming steps") are left out.
- `MODULES.md` in the repo is written only for the data folder in the repo's `.env`, never for a
  scratch folder (test runs had put test decks into it); restored from DATA_DIR.
- Checked on copies of the real database through the queue with Claude: text PDF 3 requests /
  7 concepts, the picture PDF 12 requests (6 images) / 24 concepts, pasted notes 4 / 10 — every
  concept taught, every name found in its source, in order, 0 JS errors; fake-AI count with
  Claude running out mid-build: 16 requests. All screens, both themes: 0 JS errors. 219 server
  tests, reader tests 3/3.

### Fixed — decks were raw slide text with template questions (2026-09-29)
- A slide PDF the reader could read fully was saved with **no AI at all**: slide titles as terms,
  bullets pasted as definitions, template questions. Pasted/Word material was extracted word for
  word, also with template questions.
- New **teaching pass** at the end of every material build (Claude online, Qwen offline): the
  proper term, a clear definition and example (`fact`), a plain-words explanation and "don't mix
  this up" (`guide`), items/steps where the source has them, 3 real questions with reasons, plus
  the key terms hidden inside a slide. The recall questions (term ↔ definition) are kept, built
  from the clean definitions. No new data fields.
- A **tidy step** folds duplicates and fragments into the concept they belong to (their questions
  move with them); every slide keeps at least one concept of its own.
- Qwen: one concept per request and replies that stop early are kept (it often ended after the
  first item of a list, and the whole batch was thrown away); one retry per batch. A batch that
  still fails keeps its concepts as read, bullets tidied.
- Uploading a PDF that already has a deck now offers "Build a fresh deck" (the old deck stays).
- Checked on copies of the real database: the 8-slide "What is machine learning" PDF → 10 taught
  concepts with Claude (~90 s), 10 with Qwen (9/10 taught before the retry was added); 7 lines of
  pasted notes → 15 concepts, 13 fragments folded. 0 JS errors. Reader tests 3/3.

- Loading screen tagline: "Study smarter. Remember longer." (was "Spatial study & concept horizons").

### Added — build queue (2026-09-29)
- "Build the deck" now adds the module to a **build queue** and clears the form (the subject stays
  chosen), so the next module can be set up while one builds. Jobs run one at a time; each has
  its status and progress at the top of New deck, waiting ones can be removed, finished ones have
  Open. The sidebar's New deck shows how many are building or waiting. A finished build opens
  its deck only when nothing else is queued and you are not setting up another one.
- The queue is in memory only; closing MonoSpace with builds pending asks first.
- `build()` now takes a job (name, subject, material, files, notes, flashcards) instead of reading
  the form; what it builds and saves is unchanged.
- Checked in headless Edge on a copy of the real database (AI step stubbed): 3 queued, 1 removed,
  2 built in order into the chosen subject and saved; 0 JS errors. Reader tests 3/3.

### Added — move decks between subjects; better games (2026-09-29)
- **Drag a deck onto another subject** in the sidebar (a closed subject opens as you hover) or
  in the Library; also "Move to…" on each deck card's "…" menu. Only the deck's `folderId` in
  `library` changes.
- **60-second sprint** now has a button (Test & games); it existed with none.
- Sprint picks weak, unseen and often-missed concepts more often, never repeats within the last
  few questions, and draws wrong answers from the same topic first (no duplicate options).
- Matching shows a live timer and mistakes. Sprint and matching reports list what you missed and
  offer "Play again".
- Checked in headless Edge on a copy of the real database: drag in sidebar and Library, Move to…,
  sprint (14 answers, no repeats), matching, both reports and Play again; only the moved deck's
  entry changed; 0 JS errors. Reader tests 3/3.

- Loading screen now stays about 10 s (was at least 1.2 s); a click or any key skips it.

### Changed — native app window (2026-09-29)
- MonoSpace.exe now opens its own native window (pywebview + Microsoft WebView2) instead of an
  Edge app window, so the taskbar and title bar show MonoSpace and its orb icon (Edge showed its
  own cached icon). Edge app mode, then the default browser, remain as fallbacks. Downloads
  (backups) allowed; external links open in the browser. `<link rel="icon">` added.

### Changed — reorganised app, branding, loading screen (Elisha, 2026-09-29)
- **Layout:** sidebar = logo, Home (Today), Library, Review (due count), New deck; Subjects
  (folders collapsed except the current one, one line per deck with a due badge, Archive last);
  Backups, Appearance, Settings at the bottom. Today: one next action, recently studied decks,
  progress at a glance. Library: subjects as sections of deck cards, search + subject filter;
  folder rename/colour/delete live here. Review: everything due, by deck. Deck page: Study,
  Teach me, "Test & games" and "What to study" menus, a "…" menu for rare actions; tabs
  Overview · Guide · Terms · Cards · Manage. Settings: AI status, global study options (moved
  from each deck's "Session options"), appearance, version.
- **Backups view:** download / restore a backup file, the server's snapshot list, "Take a
  snapshot now". Server: `GET /api/backups`, `POST /api/backups/snapshot` (manual snapshots are
  never pruned; nothing can be deleted or restored from the app — restoring stays
  `python -m server.restore`). `/api/health` reports the version.
- **Branding:** icon, logo and README cover from Elisha's orb artwork
  (`assets/monospace-logo-source.png`, `packaging/make_icon.py`); exe, installer, window and
  favicon use it.
- **Loading screen** (`app/splash.css`, `app/splash.js`): rotating wireframe sphere, glowing core,
  orbiting moons, MONOSPACE title, "Loading your decks…"; at least 1.2 s, hides when boot finishes
  (or after 8 s), then stops and removes itself; still frame with reduced motion.
- **Data:** no stored key or JSON shape changed; old backups restore as before. Checked on a copy
  of the real database in headless Edge: 74/74 browse checks with kv/kv_history unchanged, 7/7
  write checks (only the expected keys changed), a backup download → restore round trip identical,
  contrast ≥ 4.5:1 in all presets at 1280/1440/1920, 0 JS errors, 0 non-local requests; reader
  tests 3/3; 215 server tests. A safety snapshot was taken first
  (`drill-20260929-153138-pre-restructure.db`).
- Found, not fixed: `startSprint()` (the 60-second sprint) has no button; true before this change.

### Added — MonoSpace 1.0.0 for Windows (2026-09-29)
- `MonoSpace.exe` (server/launcher.py, PyInstaller): runs the server in-process on 127.0.0.1
  and opens the app in its own window (Edge app mode, private profile). Closing the last window
  stops the server cleanly; a second launch opens another window, never a second server; a busy
  port → the next free one. First run: a small dialog chooses the data folder (default
  %USERPROFILE%\MonoSpaceData) and writes %APPDATA%\MonoSpace\settings.env. Logs in
  %LOCALAPPDATA%\MonoSpace\logs. `MONOSPACE_HOME=<folder>` redirects all of it for tests.
- Downloads built by `packaging\build.ps1`: `MonoSpace-Setup.exe` (Inno Setup, per-user, no
  admin, Start menu + desktop icon; the uninstaller never removes data or settings) and
  `MonoSpace-1.0.0-portable.zip`. Unsigned (SmartScreen: "More info → Run anyway").
- App icon (assets/monospace.ico), also served as /favicon.ico. 205 server tests.
- Elisha's data moved to a new folder name: `OneDrive\MonoSpaceData` is a verified copy of
  `DrillData` (every file byte-identical, every table row-identical, import verifier PASS);
  `.env` points at it. `DrillData` is left untouched as a backup.

### Removed (Elisha, 2026-09-29: MonoSpace is local-only, free and open source, no sign-in)
- Phase 9 (Google sign-in, accounts, one database per person) and Phase 8 (phone access over
  Tailscale with a PIN). Deleted server/google_auth.py, accounts.py, phone.py, pin.py,
  tools/phone-firewall.ps1 and their tests; no PHONE_*, AUTH_MODE, GOOGLE_* settings or --user
  flags. The server binds 127.0.0.1, answers loopback only, checks Host and Origin, one DATA_DIR.
  Kept: security headers on every response (CSP form-action now 'self'), tools/check_secrets.py.
  Any accounts.db / phone-access.db / users\ left in a DATA_DIR are untouched and not read.

### Changed
- App: **MonoSpace** rename and premium redesign (app/index.html + Inter font vendored, OFL).
  Phase 9 app code removed. Title, wordmark, dialogs and toasts say MonoSpace; new backups
  download as `monospace-backup-<date>.json`; old Drill backups are still accepted; store keys
  unchanged. New presets: "MonoSpace" (dark, default), "MonoSpace Light", "Neutral" (old ones
  kept, plus user-saved presets). Near-black gradient, glass bars, card sheen, 180 ms
  transitions, visible focus rings. One-time switch on first start: your colours are kept as
  "Classic (my colours)", MonoSpace is turned on, prefs get `msTheme:1` (written once; never when
  prefs failed to load). Checked in headless Edge: text and muted text ≥ 4.5:1 in all three new
  presets, 0 JS errors, 0 non-local requests, reader tests 3/3.
- Renamed to **MonoSpace** (server side): start.bat, console messages, placeholder page,
  MODULES.md header, the claude -p system prompt, log names, package.json. Unchanged for
  compatibility: store keys, drill.db and its tables, drill-<ts>.db snapshots, DATA_DIR.
- README rewritten as an install guide; MIT LICENSE added.

### Added
- `tools/export_public.py`: makes the clean public copy (no history; leaves out CLAUDE.md, .claude/,
  PLAN/DATA-MIGRATION/SETUP-GUIDE, legacy/, the real course fixtures, CHANGELOG/MODULES), then
  scans it for personal markers, course material and secrets. The reader test skips fixtures
  that aren't present. Comments and test names made generic (no personal names or paths).
- Phase 9 (app, marked "LOCAL PORT (Phase 9)"): with AUTH_MODE=google, an account chip (initials,
  email on hover, no image) opens "Account & security": signed in as / since / ends, active
  sessions with per-session Sign out and "Sign out all other devices", the last 20 sign-in events,
  Sign out, and a note on Google 2-Step Verification. Any 401 `auth_required` shows "You've been
  signed out — sign in again" and loads the sign-in page; a 401 is a read failure, never empty
  data, and nothing is written. With AUTH_MODE=off nothing changes. Checked offline in headless
  Edge with a stand-in Google: 24/24 + 3/3 checks, 0 CSP violations, 0 other hosts.
- Phase 9 (server): Google sign-in, one database per person. `AUTH_MODE=off|google` (default off
  = unchanged). google: every request, this PC included, needs a session; the server refuses to
  start without `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (in `.env` only). OpenID Connect code
  flow + PKCE, state bound to the browser, nonce, id_token claims checked, approved emails only,
  Google account id pinned per email; standard library only. Sessions in `DATA_DIR\accounts.db`
  (hashed), HttpOnly SameSite=Strict cookie, exactly 7 days, checked locally (works offline),
  revocable instantly; sign-in events logged; rate limits per IP. The `--existing-data` account
  (Elisha) uses DATA_DIR's existing drill.db/modules/backups in place; others get
  `DATA_DIR\users\<id>\`. `python -m server.accounts allow|disallow|list|sessions|revoke-all|events`;
  `/api/auth/*` for the account page; `--user` on importer/restore/modules/verify_import; phone PIN
  bound to an account. Security headers on every response (CSP, nosniff, no-referrer, DENY),
  checked in headless Edge with the real app and pdf.js (0 violations). `tools/check_secrets.py`
  scans the repo and git history: no secrets found. 277 tests.
- Phase 8 (server): phone access over Tailscale. `PHONE_ACCESS=off|on` (default off = this PC
  only, as before). On: only this PC and Tailscale addresses are answered (`PHONE_ALLOW_LAN=on`
  adds home Wi-Fi); everyone else gets 403 first. The PC's Tailscale names are detected
  automatically (+ `PHONE_HOSTS`). Every other device needs a PIN: `python -m server.pin
  set|revoke-all|status`; scrypt hash and hashed 30-day sessions in `DATA_DIR\phone-access.db`;
  5 wrong PINs → 15-minute lockout; changing the PIN signs every phone out. Offline sign-in page
  served by the server. `tools\phone-firewall.ps1` adds a Tailscale-only firewall rule.
- Phase 6, app side (marked "LOCAL PORT" in app/index.html; PLAN Phase 6 asks for it): a build
  from exactly one PDF first sends it to `/api/modules`. The same PDF as an existing deck →
  "No changes: this is the same PDF as your deck “…”" and that deck opens; nothing is built.
  Otherwise it builds as before, records the deck, and logs "First upload of this module" or
  "Changes since the last upload: added …; changed …; removed …". If the library can't be
  reached, it builds anyway. Multi-file or pasted-text builds are not checked or recorded.
- Phase 6 (server side): module library, `server/modules.py`. `POST /api/modules` takes the
  raw PDF (streamed to disk, up to 400 MB), fingerprints it with SHA-256 and answers
  `known:true` + the deck for a file seen before (the app says "no changes" and skips the
  build), or stores it in `DATA_DIR\modules\` (never overwriting: a different file with the
  same name gets `-<sha8>`, an identical one is reused). `POST /api/modules/{sha}/deck
  {deck_id}` records the built deck, reading its terms and coverage from `kv` itself (the
  app sends only the id), and returns added / changed / removed term names vs the previous
  version (same file name, else same deck name; names matched with the app's `norm`,
  content = fact + items + steps). `GET /api/modules` lists them. New tables `modules`,
  `module_events` (every write logged, replaced values kept, nothing deleted). MODULES.md
  regenerated after every write, in the repo and in `DATA_DIR`. Backfill CLI:
  `python -m server.modules register <pdf> --deck <id>`. Contract in `docs/API.md`.
- Tests: `tests/server/test_modules.py` (18: known = no changes, stored and never
  overwritten, name-clash suffix, identical file reused, added/changed/removed diff,
  MODULES.md, Origin refusal, register CLI, 150 MB upload over real HTTP with peak Python
  memory under 64 MB). Test servers write MODULES.md to the scratch folder, never the repo.
- AI routing (Elisha, 2026-09-29): **Claude whenever online, Qwen only offline** — pictures
  now go to Claude too when online (image blocks through the official `claude -p
  --input-format stream-json`; real check: Module 2 slide 24's risk matrix transcribed
  exactly in 5.8 s, `model_used:"claude"`). If Claude fails online (e.g. usage limit), the
  request still falls back once to Qwen (her choice), and the badge says so.
- Phase 5 close (2026-09-29): `OLLAMA_NUM_CTX=8192` (100% GPU on the 8 GB card; 16384 ran 12%
  on the CPU). `GET /api/ai/route` says which model would answer a text request and Qwen's
  context. Teacher chat: when Qwen will answer, the module text is sized to fit 8192 tokens
  (and the oldest messages dropped if needed); Claude keeps 22,000 characters and 8 messages.
  Real check on the largest deck: before, 7,825-token prompt, reply cut off; after, 4,615
  tokens, reply complete, `ollama ps` 100% GPU.
- Phase 5: the AI router, `server/ai.py`, behind `POST /api/ai` (the 503 stub is gone; 503
  `ai_not_configured` now means "no model available at all"). Images → Qwen; text →
  `claude -p` when `CLAUDE_CLI=on` and api.anthropic.com:443 answers within 2 s; otherwise
  Qwen; a failed Claude call is retried once on Qwen (`fallback_from:"claude"`). Always
  Anthropic's shape plus `model_used`; `done_reason:"length"` / Claude `max_tokens` →
  `stop_reason:"max_tokens"`. `claude -p` (flags checked on 2.1.258): prompt on stdin, empty
  temp folder, `--tools ""`, `--max-turns 1`, JSON, no session saved, API-key variables
  removed from its environment, at most 2 at once. Ollama: `num_ctx` from `.env`,
  `think:false`, `truncate:false` + `shift:false` so an oversize prompt is refused with its
  exact token count (400 `invalid_request_error`), never cut. Contract in `docs/API.md`.
  New optional settings: `OLLAMA_TIMEOUT`, `CLAUDE_MODEL`, `CLAUDE_TIMEOUT`,
  `CLAUDE_REACH_HOST`; the AI settings can be overridden by process environment variables.
- `app/index.html`: model badge (bottom-left, "AI: Claude" / "AI: Qwen" / "AI: Qwen (Claude
  failed)"): one call in `claudeRawCall`'s success path plus a `modelBadge` function (16
  added lines, nothing else changed). Reader tests 3/3.
- Tests: `tests/server/test_ai.py` (21, fake Ollama + fake `claude` program
  `tests/server/fake_claude.py`); every server test now points the router at a closed port
  with `CLAUDE_CLI=off` (conftest), so no test reaches the real models.
- Real checks 2026-09-28 (scratch DATA_DIR): Qwen and `claude -p` answer through the server;
  40,000-character prompt reached `claude -p` whole; Qwen near-limit prompt whole, over-limit
  refused; Module 2 slide 24 transcribed by Qwen; `ollama ps` **not** 100% GPU at 16384
  (12%/88%), 100% at 8192 — see OFFLINE-AI.md.
- Phase 4: `app/index.html` = the legacy app with only the two seams swapped plus vendored
  assets (diff vs legacy: 32 insertions, 46 deletions). `store.get/set/del` → `/api/store`
  (server is the only store, "Saved on this PC"); `claudeRawCall` → `/api/ai`, same body, no
  API key, no `navigator.onLine` check, `ai_not_configured` fails at once. pdf.js 3.11.174 in
  `app/vendor/pdfjs/` (sha512 = cdnjs SRI), fonts in `app/vendor/fonts/` (OFL). No `http(s)://`
  left in `app/index.html`. Checked in headless Edge with every host but localhost blocked, on
  a scratch copy of the database: all requests local, 0 failed; 18/18 decks match; a study
  session saved and survived a browser restart; pdf.js ran in a real worker; reader tests 3/3.
- `tools/verify_import.py` (stdlib only, read-only: `drill.db` opened `mode=ro`, files `rb`):
  independent of `server/importer.py`. Per deck, expected (backup files, merged by id) vs found
  (drill.db) for concepts, questions, flashcards, study-guide entries, problem courses/problems,
  progress records and folder, cross-checked against INVENTORY.md and its SHA-256s; deep and
  byte-level comparison of every `deck:`/`prog:`/`library`/`prefs`/`exam:` value, with Elisha's
  decisions recomputed as the only allowed differences; extra keys, `kv_history`, import notes
  and applied decisions checked. Exit 1 on any mismatch. `--after-study` for Phase 7 (more is
  allowed, nothing from the backups may be missing).
- Phase 3: local server and database (`server/`, `start.bat`, `requirements*.txt`,
  `pytest.ini`, `tests/server/`, `docs/API.md`).
  - **Stack decision: Python 3.12 + FastAPI 0.141 + uvicorn 0.54 + built-in `sqlite3`**
    (the default in ARCHITECTURE.md). Repo-local `.venv` (gitignored); runtime pins in
    `requirements.txt`, test pins (pytest, httpx2 for Starlette's TestClient) in
    `requirements-dev.txt`. Settings are read only from `.env`; a process environment
    variable overrides a `.env` value (used by the tests for a scratch DATA_DIR).
  - Server on 127.0.0.1:PORT only; serves `app/` (placeholder page until Phase 4). Store API
    `GET/PUT/DELETE /api/store/{key}`, `GET /api/store?prefix=`; contract in `docs/API.md`,
    mapped 1:1 to the legacy `store.get/set/del`. Values stored as the exact JSON text
    sent; missing key = 404, stored `null` = 200 `null`. Every overwrite and delete copies
    the old value to `kv_history`; an identical write is a no-op. WAL, one transaction per
    write. `/api/ai` is a 503 stub (`ai_not_configured`) until Phase 5. Refuses to start if
    `DATA_DIR` is inside the repo, missing or relative. Host/Origin checks so other
    websites cannot write. One process owns DATA_DIR at a time (OS lock on
    `DATA_DIR\drill-server.lock`).
  - Snapshots with SQLite's backup API on every start and every 24 h while running:
    `DATA_DIR\backups\drill-YYYYMMDD-HHMMSS.db`, newest `BACKUP_KEEP` kept; only that exact
    pattern is pruned. Pre-import / pre-restore safety snapshots are never pruned.
  - Restore CLI `python -m server.restore <snapshot>`: refuses while the server runs, shows
    what changes, requires typing `yes`, snapshots the current DB first.
  - Importer `python -m server.importer` / `POST /api/import`: reads every
    `DATA_DIR\import\drill-backup-*.json` read-only (SHA-256 checked before and after),
    snapshots first (only when it will write), merges oldest-exported first (Drill's `mergeDeck` and `norm` ported
    exactly; per-concept further-along progress; library order, colours, names and folders
    kept), then applies Elisha's decisions from `DATA_DIR\import-decisions.json` in a
    second transaction, each once. Idempotent. Details: DATA-MIGRATION.md → "How the
    import works".
  - `start.bat` (double-click): creates `.venv` and installs requirements on first run
    (and when `requirements.txt` changes), starts the server, opens the browser once it
    answers.
  - Tests (pytest) on synthetic data in temp folders, incl. a real-HTTP uvicorn test for
    URL decoding (Starlette's TestClient decodes paths twice, so `%` keys are tested there).
  - Review fixes (Phase 3 review, NOT READY → fixed):
    - **Rule 2: the importer asks before changing existing data.** It now plans everything
      in memory first (merge + not-yet-applied decisions) and lists keys to add, each
      existing key that would change with what changes (concepts added/replaced,
      flashcards, progress records replaced and by which tie-break, deck-level fields,
      nCon/nQ, folders, library entries), and unchanged keys. Adding needs no
      confirmation. Changing an existing key needs a typed `yes` in the CLI (`--yes` for
      scripts); `POST /api/import` never changes one and answers 409
      `confirmation_required` with the plan. A no-op run writes nothing and takes no
      snapshot. A failing check or decision now writes nothing at all (previously the merge
      was already committed). A guard stops any plan that would drop a folder, deck,
      concept, flashcard or progress record.
    - **Origin check:** `Origin: null` is no longer exempt; a PUT/DELETE/POST carrying any
      Origin other than the server's own (`http://localhost:<port>` /
      `http://127.0.0.1:<port>`) gets 403.
    - Progress records without `box` are compared the way the app's `migrate()` reads
      them (stored verbatim). merge_prog stops, writing nothing, if either side's progress,
      `m` or a record is not an object, so the file's `m` can never be dropped.
    - The merge keeps an existing deck's `name` (like the library entry), so a fuller file
      copy cannot undo a rename inside `deck.name`.
    - DATA-MIGRATION.md: the deck-level progress rule is described accurately (Drill gives
      a tie to the backup; the import gives it to the database).
    - Tests use invented names only.
    - `start.bat`: if requirements changed but cannot be installed (offline), it warns and
      starts with the existing `.venv`. CLAUDE.md/README: the first run needs internet
      once.
- Phase 2: slide-reader regression test. `npm test` reads the reader out of
  `legacy/drill-study-app.html` at runtime (never copied into the test), runs it on
  `tests/fixtures/` in the app's own order — `slidesFromUpload`, then the activity-slide
  step `setAsideActivities`, then the self-check `auditSlides` (the opening of the app's
  `resolveSlides`; the test checks the app still opens that way and stops with exit code 2
  if not) — and compares the terms left after activity slides are set aside with
  `tests/golden/`: term names, topics, items, steps and pages, plus content/image/skipped
  slides; the self-check must flag zero slides. The number of slides/terms set aside is
  printed. `--html <path>` points it at another copy (Phase 4:
  `npm test -- --html app/index.html`). Node only, no npm dependencies, no network.
  Files: `package.json`, `tests/run-reader-tests.js`, `tests/lib/extract-reader.js`.
  Result 2026-09-28: Module 2 → 30 terms, Module 3 → 23 terms, all identical, 0 set
  aside on both; a one-line break in `toLines` and a one-line break in
  `setAsideActivities` (set aside every content slide) each fail both modules (exit code 1).
  Neither real module has an activity slide, so on its own this missed a break that stops
  `setAsideActivities` setting activities aside. **Closed by a synthetic fixture:**
  - New fixture + golden file (Elisha's approval, 2026-09-28):
    `tests/fixtures/synthetic-activity-text.json` and
    `tests/golden/synthetic-activity.expected.json`. **Why:** without an activity slide
    in any fixture, nothing checked that activities are set aside. The fixture is
    hand-built, in the same `{page: {items, imgs}}` shape, with invented text only (no
    course content, no personal data; marked SYNTHETIC in `tests/fixtures/README.md` and in
    the golden file's `note`). Its six pages are a cover, a divider and three one-term
    content slides (Widget, Gadget, Sprocket), plus slide 5 "ACTIVITY 1" ("Submit your
    answers before Friday."). The golden file was generated from the legacy reader
    only after checking by hand that its output is the intended reading: 3 terms kept,
    slide 5 and its term "Activity 1" set aside, 0 self-check flags.
  - The test now also asserts which slides are set aside, exactly (page, title, reason,
    terms, in order), against a new golden field, `setAside`. A golden file without it
    expects none, so Modules 2 and 3 are held to 0 set aside. Their fixtures and golden
    files are unchanged. `npm test` runs all three fixtures.
  - Proof: with `if(!why) return;` → `return;` in `setAsideActivities` (activities kept),
    the synthetic fixture FAILS (extra term "Activity 1", slide 5 not set aside), exit
    code 1. Before this change the same break passed with exit code 0. The earlier breaks
    still fail: `toLines` 1, set-aside-everything 1, resolveSlides reordered 2.
- Starter kit: CLAUDE.md, docs/ (PLAN, ARCHITECTURE, DATA-MIGRATION, OFFLINE-AI),
  six subagents in .claude/agents/, legacy app frozen in legacy/, reader regression
  fixtures and golden files for IA Modules 2 and 3.

### Fixed
- Reader (app/index.html `slidesFromUpload`): a full-slide background image no longer counts
  as a picture. Why: re-capturing Module 3 from the real PDF showed every page has exactly one
  image, a Canva background (118% of the page area), so the title-only dividers p6 "Purpose of
  Security Control" and p12 "Types of Security Controls" were classed as picture slides and
  sent to the AI, and terms 2–10 got the wrong topic. The picture count now follows the
  drawing transform in the operator list and skips images covering >= 90% of the page
  (`pg.view`). Module 2's real pictures cover 12–28%, so slide 24 is still a picture slide.
  This was the "Found, not fixed" item on the Module 3 fixture (Elisha's advance decision,
  2026-09-28). Golden files unchanged.
- Fixtures `module2-text.json` and `module3-text.json` re-captured from the module PDFs
  (Elisha's approval) with pdf.js 3.11.174: text items byte-identical to before; each page is
  now `{items, imgs, view, images}` (imgs = image paint operations, view = page box,
  images = the transform at each image paint). The test replays those transforms so the
  background rule is exercised. Module 3 is no longer a bare items array.

### Changed
- Reader test: default target is now `app/index.html` (`--html <file>` for any other).
  `legacy/drill-study-app.html` stays the frozen reference; it still counts Canva
  backgrounds as pictures and so fails the Module 3 fixture (imageSlides [6,12], topics) —
  expected, and proof the test catches that bug.
- Server (Phase 4 follow-up, clean browser console): `GET /api/store/{key}` for a missing key
  answers **204 No Content** instead of 404 (a stored JSON `null` is still 200 `null`;
  DELETE of a missing key is still 404); `GET /favicon.ico` answers 204 unless
  `app/favicon.ico` exists; `.woff2` is served as `font/woff2`; every `/api/*` response has
  `Cache-Control: no-store`. docs/API.md and the server tests updated.
- No API key: Qwen3.5 9B via Ollama by default, Claude via the official `claude -p` when online.
- Personal data moved out of the repo to `DATA_DIR` (OneDrive\DrillData) with automatic snapshots.
- Legacy app updated: backup v2 includes settings and unfinished Test papers; restore
  merges deck content and can never shrink a deck.
- Added docs/SETUP-GUIDE.md (step by step).
- Added .gitattributes (`* -text`): Git no longer converts line endings, so the frozen
  legacy app and test fixtures stay byte-for-byte identical on every checkout.
- docs/DATA-MIGRATION.md: defined "further-along" for one concept's progress record —
  higher box wins; if tied, more right answers; if still tied, most recently seen.
- docs/DATA-MIGRATION.md: third "further-along" tie-break is now the later next-review
  date (`due`) — Drill keeps no per-concept "last seen" date (`seen` is a count). The
  wrong claim that this is "the same rule Drill's own restore uses" is replaced by an
  accurate description: restore merges content the same way but keeps one side's
  progress for the whole deck, chosen by `asked`.
- docs/PLAN.md and docs/DATA-MIGRATION.md: any `drill-backup-*.json` file name is accepted.
- docs/PLAN.md: Phase 0 boxes ticked (verified 2026-09-28).
- docs/DATA-MIGRATION.md: "further-along" completed (Elisha, 2026-09-28) — a concept
  with a record in only one copy keeps that record; if next-review dates also tie, the
  record from the fuller deck copy is kept.

### Migration
- Phase 3 import into `DATA_DIR\drill.db` (2026-09-28): 1 file
  (`drill-backup-2026-09-28.json`, sha256 `e75f6c96…0ba9`, unchanged after import).
  29 keys written as in the file (18 `deck:`, 9 `prog:`, `prefs`, `library`), then
  Elisha's decisions: `muaicdxx9pud` renamed "IA Module 3 (old build)" and moved to a new
  "Archive" folder (`f-archive`, last); CLO3/TLO7–9 confirmed absent from `mui02dwojkee`;
  progress carry-over compared all 6 shared concepts and `mui02dwojkee`'s record won each
  (every `muaicdxx9pud` record is box 0, right 0), so `prog:mui02dwojkee` is unchanged;
  "rebuild from PDF after Phase 4" (2 decks) and "rename later" (5 decks) recorded in
  `import_notes`. Totals read back: 18 decks, 506 concepts, 1,859 questions, 506
  flashcards, 19 guide entries, 4 problem courses, 217 progress records (= INVENTORY.md).
  Second run: 0 kv writes, 0 history rows.
- Phase 1 done: `DATA_DIR\import\INVENTORY.md` built from the backup `drill-backup-2026-09-28.json`
  (18 decks, 506 concepts, 1,859 questions, 506 flashcards, 217 progress records). Nothing
  was imported. Elisha's import decisions are recorded in INVENTORY.md:
  - "IA Module 3": `mui02dwojkee` is the real deck; `muaicdxx9pud` is archived as
    "IA Module 3 (old build)" and progress on matching concept names carries over.
  - NLP Modules 2 and 3 are to be rebuilt from their PDFs after Phase 4.
  - The same-named Module 1/2 decks stay separate and are marked "rename later".

- app/index.html: restore dialog, backup note and comment now say what restore really does:
  deck content is only added to, and progress is taken per deck from whichever side has
  answered more questions (Elisha, 2026-09-28; outside the two seams by her decision).

### Fixed (visual polish, Elisha 2026-09-29; app/index.html, marked "LOCAL PORT (polish)")
- Measured in headless Edge, both themes, 1440x900 and 1280x720 (before → after):
  - dark primary buttons: text contrast 3.1 → 6.2:1;
  - light muted text: 2.7–3.1 → 4.6–5.2:1; light sidebar muted: 4.0 → 6.3:1;
  - the study bar no longer covers the question card (15 px overlap → 0) or the sidebar, and its
    stats are centred on the content;
  - "Ask the teacher" no longer hides page ends (more bottom space);
  - big buttons line up with their neighbours (a legacy `.big` class clash);
  - home-page text 8.5–10.9 px → 11–12.5 px; sidebar folder names no longer cut off;
  - New deck labels aligned; text boxes and the flashcard hint use the normal font.

### Fixed (usability pass, Elisha 2026-09-29; app/index.html, marked "LOCAL PORT")
- Server unreachable at startup: the app says "Can't reach the Drill server" and writes nothing,
  instead of opening an empty library and saving it (or default settings) over the real ones;
  a restore no longer treats an unanswered settings read as "no settings".
- A failed save now shows "Not saved — the Drill server isn't answering…" (was silent).
- The unused "Anthropic API key" card is hidden (no key is ever used).
- Online/offline text says where AI answers come from (Claude online, Qwen on this PC offline);
  messages no longer talk about "this browser's storage" or "your connection".
- After a revised module is built, the "changes since the last upload" summary also shows as a
  toast (the build log is off-screen once the deck opens).
- Checked in headless Edge on a scratch copy: normal start, a 503 on `library` at start (dialog,
  0 writes), and a save with the server down (toast).
- Phone layout (Phase 8 mobile part) stopped at Elisha's request; the phone-access server
  remains, off by default.

### Found, not fixed
- The same-PDF check ignores the page range.
- Deleting a key that was never stored (e.g. `prog:` of a never-studied deck) logs a 404 line
  in the browser console; harmless.
