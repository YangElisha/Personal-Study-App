"""Publish the build in dist\\ as a GitHub Release, so installed copies offer it as an update.

    python tools/release.py --notes NOTES.md [--repo owner/repo] [--dry-run]

The release gets MonoSpace-Setup.exe, MonoSpace-Setup.json (build, built_at, sha256: how the app
knows it's newer and checks the download) and the portable zip, tagged v<version>, titled
"MonoSpace <version>", with NOTES.md as "What's new" (shown in the app before updating).

Before running:
  1. Raise __version__ in server/__init__.py (each release needs a new version).
  2. Build: powershell -ExecutionPolicy Bypass -File packaging\\build.ps1
     with the public repo in packaging\\update-repo.txt, so the build itself checks that repo.
  3. Write the notes for students, not developers (docs/RELEASING.md).

Uses the GitHub CLI (gh) when installed and signed in; otherwise prints how to publish the same
files on github.com. Nothing is published with --dry-run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT))
from server import __version__  # noqa: E402


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notes", required=True, help="Markdown file: what's new, for students")
    ap.add_argument("--repo", help="owner/repo (default: the update repo the build was made with)")
    ap.add_argument("--dry-run", action="store_true", help="check everything, publish nothing")
    a = ap.parse_args()

    setup, info_file = DIST / "MonoSpace-Setup.exe", DIST / "MonoSpace-Setup.json"
    zips = sorted(DIST.glob(f"MonoSpace-{__version__}-portable.zip"))
    if not setup.is_file() or not info_file.is_file():
        sys.exit("No build in dist\\ - run packaging\\build.ps1 first.")
    info = json.loads(info_file.read_text(encoding="utf-8-sig"))
    notes = Path(a.notes)
    problems = []
    if info.get("sha256") != sha256(setup):
        problems.append("dist\\MonoSpace-Setup.exe doesn't match MonoSpace-Setup.json - rebuild.")
    if info.get("version") != __version__:
        problems.append(f"the build is version {info.get('version')}, the code says {__version__} - rebuild.")
    repo = a.repo or info.get("update_repo") or ""
    if not repo:
        problems.append("no repo: pass --repo owner/repo, or build with packaging\\update-repo.txt.")
    elif info.get("update_repo") != repo:
        problems.append(f"this build checks '{info.get('update_repo') or 'no repo'}' for updates, not '{repo}' - "
                        "put the repo in packaging\\update-repo.txt and rebuild, or installed copies won't see "
                        "later releases.")
    if not notes.is_file() or not notes.read_text(encoding="utf-8").strip():
        problems.append(f"no release notes at {notes}.")
    if problems:
        print("Not released:\n  - " + "\n  - ".join(problems))
        return 1

    tag = f"v{__version__}"
    files = [str(setup), str(info_file)] + [str(z) for z in zips]
    cmd = ["gh", "release", "create", tag, *files, "--repo", repo, "--title", f"MonoSpace {__version__}",
           "--notes-file", str(notes)]
    print(f"Release {tag} of {repo}: build {info.get('build')} (commit {info.get('commit')})")
    for f in files:
        print("  ", Path(f).name)
    if a.dry_run:
        print("Dry run - would run:\n  " + subprocess.list2cmdline(cmd))
        return 0
    if not shutil.which("gh"):
        print("\nThe GitHub CLI (gh) isn't installed. Publish by hand instead:\n"
              f"  1. https://github.com/{repo}/releases/new\n"
              f"  2. Tag: {tag}   Title: MonoSpace {__version__}\n"
              f"  3. Description: paste {notes}\n"
              "  4. Attach: " + ", ".join(Path(f).name for f in files) + "  (all from dist\\)\n"
              "  5. Publish release (not a pre-release: the app only looks at the latest release)")
        return 0
    if subprocess.run(["gh", "release", "view", tag, "--repo", repo], capture_output=True).returncode == 0:
        print(f"{tag} already exists - raise __version__ in server/__init__.py and rebuild.")
        return 1
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
