# Releasing an update

Installed copies of MonoSpace check the update repo's **latest GitHub Release** when they're online,
at most every 6 hours. When it's newer they show **Update ready** and a one-time notice. Tapping
either opens **What's new** (your release notes) with **Update now** / **Later**. Updating
downloads the installer, checks it against the release's checksum, takes a backup snapshot of the
database, and installs and reopens MonoSpace. People can turn the online check off in
**Settings → About**.

Nothing is checked online until a build is made **with** an update repo. While the repo is private,
builds have none, so no copy looks at GitHub. A private repo couldn't be checked anyway: GitHub
answers "not found" to anyone who isn't signed in.

## Once, when the public repo exists
1. Put the public repo's name in `packaging/update-repo.txt`, for example:
   ```
   YangElisha/MonoSpace
   ```
2. Build (`packaging\build.ps1`) and publish that build as the first release (below). Copies
   installed from **that** release onwards check for updates. Copies built before it don't know the
   repo, so they have to be reinstalled by hand once.

## Each release
1. Raise `__version__` in `server/__init__.py` (for example `1.0.0` → `1.1.0`). Every release needs a
   new version, and the tag is `v<version>`.
2. Add the changes to `CHANGELOG.md` as usual.
3. Build: `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`
4. Write the release notes in a file, for example `notes.md`. They're for **students**, not
   developers: what they'll notice and why it's better. Short headings and bullets show best in the
   app:
   ```markdown
   ## What's new
   - **Pick your teacher:** choose Claude or Qwen in Ask the teacher.
   - **Fairer marking:** answers in your own words now count, and you can mark one as correct.

   ## Fixed
   - Questions no longer show their own answer.
   ```
5. Check, then publish:
   ```
   python tools/release.py --notes notes.md --dry-run
   python tools/release.py --notes notes.md
   ```
   With the [GitHub CLI](https://cli.github.com) installed and signed in (`gh auth login`), this
   creates the release. Without it, the script prints the exact steps to do the same on github.com.
6. Publish it as a normal release, not a pre-release or draft. The app only looks at the latest
   published release.

What the release must contain (the script attaches it): `MonoSpace-Setup.exe`,
`MonoSpace-Setup.json` (written by the build: version, build id, date, sha256) and the portable
zip. If the installer and the `.json` don't match, the app refuses the download.
