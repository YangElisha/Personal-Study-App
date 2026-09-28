"""Synthetic Drill data for the server tests. Invented names only; no personal data."""
from __future__ import annotations

import json
from pathlib import Path


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def concept(cid, name, nq=2, **extra):
    return {"id": cid, "name": name, "topic": "Topic", "fact": f"About {name}.",
            "qs": [{"t": "mc", "q": f"Q{i} on {name}?", "o": ["a", "b"], "a": "a",
                    "why": "because"} for i in range(nq)], **extra}


def deck(did, name, concepts, cards=True, **extra):
    d = {"id": did, "name": name, "concepts": concepts}
    if cards:
        d["cards"] = [{"id": "k-" + c["id"], "front": c["name"], "back": c["fact"]}
                      for c in concepts]
    d.update(extra)
    return d


def entry(d, folder_id, **extra):
    cs = d["concepts"]
    return {"id": d["id"], "name": d["name"], "folderId": folder_id, "created": 1700000000000,
            "nCon": len(cs), "nQ": sum(len(c["qs"]) for c in cs), **extra}


def rec(box=1, right=1, due=1000, **kw):
    r = {"run": 1, "right": right, "wrong": 0, "done": False, "box": box, "due": due,
         "lapses": 0, "seen": 1}
    r.update(kw)
    return r


def prog(m, asked=5, **kw):
    p = {"sessions": 1, "asked": asked, "right": asked, "last": 1700000000000, "m": m,
         "teach": {"passed": {}}}
    p.update(kw)
    return p


def backup(folders, decks, progs=None, exported="2026-09-01T00:00:00.000Z", v=2,
           prefs=None, exams=None, entries=None):
    """decks: list of (deck, folder_id). progs: {deck_id: prog or None}."""
    lib_decks = entries if entries is not None else [entry(d, f) for d, f in decks]
    out = {"v": v, "exported": exported,
           "library": {"folders": folders, "decks": lib_decks},
           "decks": {d["id"]: d for d, _ in decks},
           "prog": {d["id"]: (progs or {}).get(d["id"]) for d, _ in decks}}
    if v == 2:
        out["exams"] = exams or {}
        out["prefs"] = prefs
    return out


def write_backup(import_dir: Path, name: str, obj) -> Path:
    import_dir.mkdir(parents=True, exist_ok=True)
    p = import_dir / name
    p.write_bytes(dumps(obj).encode("utf-8"))
    return p


FOLDERS = [{"id": "f-a", "name": "Alpha"}, {"id": "f-b", "name": "Beta", "color": "#123456"}]


def simple_backup(prefs=None, **kw):
    d1 = deck("d1", "Deck One", [concept("c1", "Widget"), concept("c2", "Gadget")])
    d2 = deck("d2", "Deck Two", [concept("c3", "Sprocket", nq=3)])
    return backup(FOLDERS, [(d1, "f-a"), (d2, "f-b")],
                  progs={"d1": prog({"c1": rec(box=2), "c2": rec()}), "d2": None},
                  prefs=prefs or {"theme": {"mode": "dark"}, "opt": {"timer": False}}, **kw)
