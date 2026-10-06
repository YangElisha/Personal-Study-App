# Future features

Ideas Elisha wants built later, with the design thinking so far. Newest first. When one is built,
move it to CHANGELOG.md and delete it here.

---

## "Teach it back" — you become the teacher (asked for 2026-10-06)

**The idea.** Explaining something out loud is one of the best ways to learn it, and it shows you
what you actually know. In this mode the roles flip: an AI plays a **student** who asks you
questions about a deck ("What *is* software engineering?", "Wait, why can't the waterfall model
just go back a step?"), and **you** explain. You can type, or turn on the microphone and talk.
When you finish, it tells you how deep your understanding is and what to work on.

**How it should feel.** It "locks you in", like a real conversation:
- It opens as a **focused full-screen panel** over the app, so the rest of the screen goes quiet.
  Picture a video call or a tutoring session: the "student" on one side, you on the other.
- The student has a **personality and a level**: curious first-year, confused classmate, tough
  examiner. It asks **follow-ups that probe**: "but why?", "can you give an example?", "how is
  that different from X?". It also plays dumb on purpose, so you have to be clear.
- Your **sticky notes ride along on the side**. Any notes you made about this deck or subject
  (the pinboard) are visible, so you can glance at what you've struggled with before. While
  explaining, you can pin a new one ("I couldn't explain change tolerance").
- **Mic or keyboard.** A big mic button to talk (speech to text, on this PC where possible), and a
  text box for typing. Talking should be the default, because saying it out loud is the point.

**What it gives back** (the "log" of each session, kept with the deck):
- Per concept: **Explained fully / Surface level / Missed it / Got it wrong**, judged against
  the deck's own definitions and the module text. No made-up standards.
- **Your weak side**: the specific gaps ("you described *what* incremental development is but
  not *why* it lowers the cost of change"), and what to say next time.
- **Suggestions**: "practise these 3", pin them as stickies, or start a short review of just
  those terms.
- A history over time, so you can see your explanations getting deeper.

**Building blocks already in MonoSpace.**
- The AI router (`server/ai.py`): Claude or the local AI. The supervisor pattern can grade
  explanations against the deck's definitions and the module source.
- The teacher chat drawer (Ask the teacher) for the conversation UI: the roles are reversed,
  but the plumbing is the same.
- The pinboard (`LIB.stickies`) for the sticky notes on the side.
- `deck.source` (the module text) and each concept's definition, explanation and "students
  often confuse" line, to judge depth fairly.

**Open questions to decide when building it.**
- Speech to text offline: Windows' built-in speech recognition, a local Whisper model, or the
  browser's Web Speech API (which may need the internet in WebView2)? Needs testing.
- How many questions per session, and how is a concept chosen (weakest first? the ones you
  "know" but have never explained?).
- Where the log lives: per deck (like progress), shown on the deck's Overview and in Review.
- Grading must say "not in your module" rather than penalise you for the module's own gaps.
