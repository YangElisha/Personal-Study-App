# Future features

Ideas Elisha wants built later, with the design thinking so far. Newest first. When one is built,
move it to CHANGELOG.md and delete it here.

---

## What is still open on "Teach it back" (built 2026-10-06, see CHANGELOG.md)

The mode is in. Two pieces of the original design are not:

- **Talking offline.** The mic uses the browser’s own speech recognition, which may need the internet
  inside WebView2. A local Whisper model would make talking work with the Wi-Fi off.
- **History over time.** Each session is kept (`PROG.explain`, the last 30), but nothing yet draws how
  your explanations got deeper across sessions.
