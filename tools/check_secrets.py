"""Look for secrets in the repo and in its whole git history. Read-only.

    .venv\\Scripts\\python tools\\check_secrets.py

Checks
  1. the files Git would commit (tracked + untracked, minus .gitignore'd), and
  2. every line ever added in any commit on any branch (git log -p --all),
for:
  - Anthropic keys (sk-ant-...), Google OAuth client secrets (GOCSPX-...), Google API keys
    (AIza...), private key blocks (-----BEGIN ... PRIVATE KEY-----), GitHub/Slack/AWS tokens;
  - a non-empty value assigned to a secret-looking setting (GOOGLE_CLIENT_SECRET=...,
    ANTHROPIC_API_KEY=..., *_TOKEN=..., *_PASSWORD=...);
  - a .env file ever committed;
  - the actual secret values in this PC's .env (settings whose name contains SECRET, KEY,
    TOKEN or PASSWORD), wherever they appear. The values themselves are never printed.

Exit code 0 = nothing found, 1 = something found, 2 = could not run.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PATTERNS = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("Google OAuth client secret", re.compile(r"GOCSPX-[A-Za-z0-9_\-]{10,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|github_pat_[A-Za-z0-9_]{50,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("OpenAI-style key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b")),
]
# NAME=value with a secret-looking NAME and a real-looking value (not empty, not <placeholder>)
ASSIGN = re.compile(r"^\s*(?:export\s+|set\s+)?([A-Z][A-Z0-9_]*(?:SECRET|API_KEY|TOKEN|PASSWORD)"
                    r"[A-Z0-9_]*)\s*=\s*[\"']?([^\s\"'#<>]{8,})")
SECRETY_NAME = re.compile(r"SECRET|KEY|TOKEN|PASSWORD", re.I)
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".pdf", ".db",
                 ".zip", ".pyc"}


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace')}")
    return r.stdout.decode("utf-8", errors="replace")


def env_secret_values() -> dict[str, str]:
    env = REPO / ".env"
    out = {}
    if not env.is_file():
        return out
    for raw in env.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = (x.strip() for x in line.split("=", 1))
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if SECRETY_NAME.search(k) and len(v) >= 8:
            out[k] = v
    return out


def mask(s: str) -> str:
    return f"({len(s)} chars, hidden)"


def scan_line(line: str, env_values: dict[str, str]) -> list[str]:
    found = []
    for name, rx in PATTERNS:
        m = rx.search(line)
        if m:
            found.append(f"{name}: {mask(m.group(0))}")
    m = ASSIGN.search(line)
    if m:
        found.append(f"value assigned to {m.group(1)}: {mask(m.group(2))}")
    for k, v in env_values.items():
        if v in line:
            found.append(f"the value of {k} from .env")
    return found


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        files = [f for f in git("ls-files", "-co", "--exclude-standard", "-z").split("\0") if f]
        history = git("log", "-p", "--all", "--no-color", "-U0", "--format=commit %H")
        committed_names = git("log", "--all", "--no-color", "--name-only", "--format=")
        commits = len(git("rev-list", "--all").split())
    except (RuntimeError, OSError) as e:
        print(f"CANNOT RUN: {e}")
        return 2
    env_values = env_secret_values()
    problems: list[str] = []

    for f in files:
        p = REPO / f
        if p.suffix.lower() in SKIP_SUFFIXES or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for what in scan_line(line, env_values):
                problems.append(f"working tree  {f}:{n}  {what}")

    commit, path, added = "", "", 0
    for line in history.splitlines():
        if line.startswith("commit "):
            commit = line[7:19]
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
            if Path(path).suffix.lower() in SKIP_SUFFIXES:
                continue
            for what in scan_line(line[1:], env_values):
                problems.append(f"history  {commit}  {path}  {what}")

    for name in set(committed_names.split("\n")):
        if re.search(r"(^|/)\.env$", name.strip()):
            problems.append(f"history  a file named .env was committed: {name.strip()}")

    print(f"Scanned {len(files)} files in the working tree and {added:,} added lines in "
          f"{commits} commits (all branches).")
    print(f"Secret values from .env checked for: {len(env_values)} "
          f"({', '.join(sorted(env_values)) or 'none set'})")
    if problems:
        print(f"FOUND {len(problems)} possible secret(s):")
        for p in problems:
            print("  " + p)
        return 1
    print("No secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
