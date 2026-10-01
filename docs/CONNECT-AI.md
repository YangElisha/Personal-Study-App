# Connecting your AI

MonoSpace uses two AIs:

| Slot | When it's used | Out of the box |
|---|---|---|
| **Online AI** | Whenever you're online | Claude, through the Claude Code program |
| **AI on this PC** | When you're offline, when the online AI fails or hits its limit, and when you pick it in *Ask the teacher* | Qwen, through Ollama |

You can put a different AI in either slot.

**Building a deck needs an AI.** It reads the module and writes the definitions, explanations and
questions. Without one, a slide PDF with real text gives only a rough deck in the slides' own
wording, and picture slides and notes can't be built. **Studying needs no AI**: once a deck exists,
review, flashcards, tests and games all work fully offline. **We recommend a local AI** (see "AI on
this PC" below). It has no account and no usage limits, nothing leaves your PC, and it works offline.
An online AI is optional; with both, the online one answers and the local one backs it up.

**No API keys.** An online AI is always used through that company's own command-line program,
signed in with **your own** account and plan, the same way you'd use it in a terminal. MonoSpace
never sees your password or login token.

## Where the settings are

All AI settings are lines in one text file:

- **Installed app:** `%APPDATA%\MonoSpace\settings.env`. In MonoSpace go to **Settings → AI →
  Connect a different AI → Open settings file**.
- **From source:** `.env` in the MonoSpace folder (copy `.env.example`).

Change the lines, save the file, then press **Reload AI settings** (same place). You don't have to
restart. **Settings → AI** then shows which AIs are connected, and the rest of the app uses their
names ("AI: Codex", "Ask the teacher: Codex | Llama"…).

---

## Online AI

### Claude (the default)
1. Install [Claude Code](https://claude.com/claude-code).
2. Open a terminal, run `claude` once and sign in with your Claude plan.
3. In the settings file:
   ```
   ONLINE_AI=claude
   ```
   (Older settings files say `CLAUDE_CLI=on` instead; that still works.)

Optional: `CLAUDE_MODEL=sonnet` (the default; `opus` for the largest model) and `CLAUDE_TIMEOUT=600`.

### OpenAI Codex
1. Install [Node.js](https://nodejs.org) (LTS), then in a terminal:
   `npm install -g @openai/codex`
2. Sign in with your ChatGPT plan: `codex login`
3. In the settings file:
   ```
   ONLINE_AI=codex
   ```
   Optional: `ONLINE_AI_MODEL=<model name>` to choose the model (empty = Codex's default).

MonoSpace runs `codex exec` in an empty temporary folder with `--sandbox read-only`, so Codex can't
change any of your files. Pictures (slides that are images) are sent to Codex as image files.

### Google Gemini
1. Install [Node.js](https://nodejs.org) (LTS), then: `npm install -g @google/gemini-cli`
2. Run `gemini` once in a terminal and sign in with your Google account.
3. In the settings file:
   ```
   ONLINE_AI=gemini
   ```
   Optional: `ONLINE_AI_MODEL=<model name>`.

MonoSpace sends Gemini text only. Pages that are pictures are read by the AI on this PC instead,
so keep a local AI that can read images (Qwen does).

### Any other command-line AI
If an AI has a program that takes a prompt and prints an answer, MonoSpace can use it:
```
ONLINE_AI=custom
ONLINE_AI_NAME=My AI
ONLINE_AI_COMMAND=myai ask --model big --input {prompt_file} --output {output_file}
ONLINE_AI_REACH_HOST=api.example.com:443
ONLINE_AI_SIGNIN=open a terminal and run: myai login
```
In `ONLINE_AI_COMMAND` you can use:

| Placeholder | Becomes |
|---|---|
| `{prompt_file}` | a text file holding the whole request. Leave it out and the request goes on **standard input** instead |
| `{output_file}` | the file the program writes its answer to. Leave it out and MonoSpace reads what the program **prints** |
| `{images}` | the picture files, one argument each (only with `ONLINE_AI_IMAGES=on`) |
| `{workdir}` | the empty temporary folder the program runs in |
| `{model}` | the value of `ONLINE_AI_MODEL` |

`ONLINE_AI_REACH_HOST` is what MonoSpace checks (for 2 seconds) to decide whether you're online.
Use the AI company's server, port 443.

The same placeholders also fix the Codex or Gemini settings if a new version of their program
changes its options. Use `ONLINE_AI=custom` with the command that works in your terminal.

### No online AI
```
ONLINE_AI=off
```
Everything then runs on this PC.

---

## AI on this PC

A local AI needs a reasonably strong PC: about 8 GB of graphics memory for a 7–9B model like Qwen
3.5 9B. To read slides that are **pictures**, the model must understand images (Qwen 3.5, Gemma 3,
Llama 3.2 Vision, LLaVA…). A text-only model still does everything else.

### Ollama: Qwen or any other model
1. Install [Ollama](https://ollama.com/download).
2. Download a model in a terminal, for example:
   - `ollama pull qwen3.5:9b` (the default)
   - `ollama pull gemma3:12b`
   - `ollama pull llama3.1:8b`
   - `ollama pull mistral`
3. In the settings file:
   ```
   LOCAL_AI=ollama
   OLLAMA_MODEL=gemma3:12b
   OLLAMA_NUM_CTX=8192
   ```
   Keep `OLLAMA_NUM_CTX=8192` on an 8 GB card. Raise it (16384, 32768) only if `ollama ps` still
   shows the model at 100% GPU.

The name MonoSpace shows comes from the model ("Gemma", "Llama"…). Set `LOCAL_AI_NAME=…` to choose
your own.

### LM Studio, llama.cpp, Jan, vLLM (OpenAI-compatible servers)
Any program that offers an "OpenAI-compatible" local server works:

| Program | Start its server | `LOCAL_AI_URL` |
|---|---|---|
| [LM Studio](https://lmstudio.ai) | Developer tab → load a model → Start server | `http://localhost:1234/v1` |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | `llama-server -m model.gguf --port 8080` | `http://localhost:8080/v1` |
| [Jan](https://jan.ai) | Settings → Local API Server → Start | `http://localhost:1337/v1` |
| [vLLM](https://docs.vllm.ai) | `vllm serve <model>` | `http://localhost:8000/v1` |

In the settings file:
```
LOCAL_AI=openai
LOCAL_AI_URL=http://localhost:1234/v1
LOCAL_AI_MODEL=<the model's name in that program>
LOCAL_AI_NUM_CTX=8192
```
MonoSpace asks these servers for an answer **without the model's "thinking"**. Otherwise thinking
models (Qwen 3.5, DeepSeek-R1…) can spend the whole reply thinking and return nothing. If a model
still returns nothing, turn thinking off in that program's settings, or use a non-thinking model.

### No AI on this PC
```
LOCAL_AI=off
```
Not recommended. MonoSpace then needs the online AI to build decks, so building stops working
whenever you're offline or the online AI hits its limit.

---

## How the two work together
- **Online:** the online AI answers. If it fails (signed out, usage limit, a hiccup), the AI on
  this PC answers that request instead, so a build keeps going. A usage limit pauses the online AI
  for 30 minutes and a sign-out for 5, so it isn't retried on every request. **Settings → AI** and
  the activity log (tap the AI badge, bottom left) say why, and how to fix it.
- **Supervisor:** whatever the AI on this PC wrote during a build, the online AI checks against
  your module when it's back. It confirms, corrects or flags each concept.
- **Offline:** the AI on this PC does everything.
- **Ask the teacher:** you choose which of the two answers.

## When something doesn't work
Tap the **AI badge** (bottom left) to open the activity log. Every request shows which AI answered,
how long it took and any error. **Copy report for AI** gives you all of it, ready to paste into an
AI chat. Common causes:

| You see | Fix |
|---|---|
| "… program not found" | The CLI isn't installed or isn't on PATH. Set `ONLINE_AI_PATH` to its full path |
| "… is signed out" | Sign in again in a terminal (`claude` then `/login`, `codex login`, `gemini`), then **Try … again** in the log |
| "… is not reachable at http://localhost:…" | Start the local program (Ollama, LM Studio…) or check `LOCAL_AI_URL` |
| "model … not found" | Download the model (`ollama pull …`), or fix `OLLAMA_MODEL` / `LOCAL_AI_MODEL` |
| "Prompt is too long" | Raise `OLLAMA_NUM_CTX` / `LOCAL_AI_NUM_CTX` if your graphics card has room |

## All AI settings

| Setting | Default | Meaning |
|---|---|---|
| `ONLINE_AI` | `claude` if `CLAUDE_CLI=on`, else `off` | `claude`, `codex`, `gemini`, `custom` or `off` |
| `ONLINE_AI_NAME` | the AI's name | what the app calls it |
| `ONLINE_AI_PATH` | `claude` / `codex` / `gemini` | the program, if it isn't on PATH (Claude: `CLAUDE_CLI_PATH`) |
| `ONLINE_AI_MODEL` | (its default) | model for Codex, Gemini or `{model}` (Claude: `CLAUDE_MODEL`) |
| `ONLINE_AI_COMMAND` | | the command for `ONLINE_AI=custom` |
| `ONLINE_AI_IMAGES` | on for Claude and Codex | send pictures to the online AI |
| `ONLINE_AI_REACH_HOST` | the AI's server, port 443 | how "online" is checked |
| `ONLINE_AI_SIGNIN` | | how to sign in again, shown when it's signed out |
| `CLAUDE_TIMEOUT` | `600` | seconds an online request may take (any online AI) |
| `LOCAL_AI` | `ollama` | `ollama`, `openai` or `off` |
| `LOCAL_AI_NAME` | from the model | what the app calls it |
| `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` | `http://localhost:11434`, `qwen3.5:9b`, `8192` | Ollama |
| `LOCAL_AI_URL`, `LOCAL_AI_MODEL`, `LOCAL_AI_NUM_CTX` | `http://localhost:1234/v1`, —, = `OLLAMA_NUM_CTX` | an OpenAI-compatible server |
| `OLLAMA_TIMEOUT` | `900` | seconds a local request may take (either kind) |
