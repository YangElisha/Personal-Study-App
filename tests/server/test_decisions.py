"""The user's import decisions, on a synthetic mini-backup shaped like the real case."""
from __future__ import annotations

import json
import sqlite3

import pytest
from conftest import history, kv, kv_full
from server.importer import ConfirmationRequired, ImportError_, run_import
from synth import backup, concept, deck, dumps, prog, rec, write_backup

FOLDERS = [{"id": "f-one", "name": "Subject One"}, {"id": "f-two", "name": "Subject Two"}]
SHARED = ["Guard Rails", "Watch Posts", "Safety Rule"]


def mini_backup(new_extra_concepts=()):
    old = deck("old3", "Unit 3", [concept("o1", SHARED[0]), concept("o2", SHARED[1]),
                                         concept("o3", SHARED[2]), concept("o4", "OUTCOME-A"),
                                         concept("o5", "OUTCOME-B")], source="pasted text")
    new = deck("new3", "Unit 3", [concept("n1", SHARED[0]), concept("n2", SHARED[1]),
                                         concept("n3", SHARED[2]), concept("n4", "Admin"),
                                         concept("n5", "Tech"), concept("n6", "Phys"),
                                         *new_extra_concepts], coverage={"pages": 9})
    m1a = deck("m1a", "Unit 1", [concept("a1", "Zork")])
    m1b = deck("m1b", "Unit 1", [concept("b1", "Quux")])
    nlp = deck("nlp2", "Lang 2", [concept("x1", "Frobnicate")])
    progs = {
        "old3": prog({"o1": rec(box=3, right=2, due=50),     # beats n1 on box
                      "o2": rec(box=1, right=1, due=100),    # full tie with n2 -> fuller (new3)
                      "o3": rec(box=1, right=0, due=900),    # beats n3 on due
                      "o4": rec(), "o5": rec()}, asked=1),
        "new3": prog({"n1": rec(box=1, right=1, due=10),
                      "n2": rec(box=1, right=1, due=100, seen=4),
                      "n3": rec(box=1, right=0, due=400),
                      "n4": rec(), "n5": rec(), "n6": rec()}, asked=51),
        "m1a": prog({"a1": rec()}), "m1b": None, "nlp2": None}
    return backup(FOLDERS, [(m1a, "f-one"), (old, "f-one"), (new, "f-two"), (m1b, "f-two"),
                            (nlp, "f-two")], progs=progs, exported="2031-01-02T03:04:05.678Z",
                  prefs={"theme": {"mode": "dark"}})


DECISIONS = {"decisions": [
    {"id": "old-rename", "type": "rename_deck", "deck": "old3", "name": "Unit 3 (old build)"},
    {"id": "archive-folder", "type": "add_folder", "folder": {"id": "f-archive", "name": "Archive"}},
    {"id": "old-archive", "type": "move_deck", "deck": "old3", "folder": "f-archive"},
    {"id": "no-outcomes", "type": "assert_not_in_deck", "deck": "new3",
     "concept_names": ["OUTCOME-A", "OUTCOME-B"]},
    {"id": "carry", "type": "carry_over_progress", "from": "old3", "to": "new3",
     "fuller": "new3", "concept_names": SHARED, "expect_to_records": 6},
    {"id": "n1", "type": "note", "deck": "nlp2", "note": "rebuild from PDF after Phase 4"},
    {"id": "n2", "type": "note", "deck": "m1a", "note": "rename later"},
    {"id": "n3", "type": "note", "deck": "m1b", "note": "rename later"},
]}


@pytest.fixture
def setup(settings):
    data = mini_backup()
    write_backup(settings.import_dir, "drill-backup-2031-01-02.json", data)
    settings.decisions_file.write_text(json.dumps(DECISIONS), encoding="utf-8")
    return data


def J(settings, key):
    return json.loads(kv(settings)[key])


def test_decisions_applied(settings, setup):
    data = setup
    rep = run_import(settings)
    lib = J(settings, "library")
    assert lib["folders"] == FOLDERS + [{"id": "f-archive", "name": "Archive"}]    # at the END
    old = next(e for e in lib["decks"] if e["id"] == "old3")
    assert old["name"] == "Unit 3 (old build)" and old["folderId"] == "f-archive"
    assert [e["id"] for e in lib["decks"]] == ["m1a", "old3", "new3", "m1b", "nlp2"]
    assert J(settings, "deck:old3")["name"] == "Unit 3 (old build)"
    # nothing else about the decks changed; the "rename later" decks are untouched
    assert J(settings, "deck:new3") == data["decks"]["new3"]
    assert [c["name"] for c in J(settings, "deck:new3")["concepts"]].count("OUTCOME-A") == 0
    for did in ("m1a", "m1b", "nlp2"):
        assert J(settings, f"deck:{did}") == data["decks"][did]
    assert [e for e in lib["decks"] if e["id"] in ("m1a", "m1b", "nlp2")] == \
        [e for e in data["library"]["decks"] if e["id"] in ("m1a", "m1b", "nlp2")]

    # progress carry-over
    new_m = J(settings, "prog:new3")["m"]
    src_m = data["prog"]["old3"]["m"]
    assert len(new_m) == 6
    assert new_m["n1"] == src_m["o1"]                       # higher box
    assert new_m["n2"] == data["prog"]["new3"]["m"]["n2"]   # full tie -> fuller copy (new3)
    assert new_m["n3"] == src_m["o3"]                       # later due
    assert {k: new_m[k] for k in ("n4", "n5", "n6")} == \
        {k: data["prog"]["new3"]["m"][k] for k in ("n4", "n5", "n6")}
    p_new = J(settings, "prog:new3")
    assert {k: v for k, v in p_new.items() if k != "m"} == \
        {k: v for k, v in data["prog"]["new3"].items() if k != "m"}
    assert J(settings, "prog:old3") == data["prog"]["old3"]          # keeps its own records

    text = "\n".join(rep.lines)
    assert "Guard Rails: old3/o1" in text and "->  old3 (higher box)" in text
    assert "->  new3 (fuller deck copy)" in text and "->  old3 (later next-review date)" in text
    assert "new3 progress records: 6 (unchanged count)" in text
    assert "rebuild from PDF after Phase 4" in text and "rename later" in text

    # kv_history holds the untouched imported values
    assert history(settings, "library") == [dumps(data["library"])]
    assert history(settings, "deck:old3") == [dumps(data["decks"]["old3"])]
    assert history(settings, "prog:new3") == [dumps(data["prog"]["new3"])]
    assert len(history(settings)) == 3

    conn = sqlite3.connect(settings.db_path)
    try:
        notes = conn.execute("SELECT deck_id, note FROM import_notes ORDER BY deck_id").fetchall()
        applied = [r[0] for r in conn.execute("SELECT id FROM import_decisions_applied ORDER BY id")]
    finally:
        conn.close()
    assert notes == [("m1a", "rename later"), ("m1b", "rename later"),
                     ("nlp2", "rebuild from PDF after Phase 4")]
    assert applied == ["archive-folder", "carry", "old-archive", "old-rename"]


def test_decisions_second_run_changes_nothing(settings, setup):
    run_import(settings)
    before = kv_full(settings)
    h = len(history(settings))
    rep = run_import(settings)
    assert rep.kv_writes == 0 and rep.history_rows == 0
    assert kv_full(settings) == before and len(history(settings)) == h
    assert "already applied" in "\n".join(rep.lines)


def test_decisions_are_not_reapplied_over_later_app_changes(settings, setup, make_client):
    run_import(settings)
    lib = J(settings, "library")
    next(e for e in lib["decks"] if e["id"] == "old3")["name"] = "My own name"
    with make_client() as c:
        c.put("/api/store/library", content=dumps(lib).encode("utf-8"))
    rep = run_import(settings)
    assert rep.kv_writes == 0
    assert next(e for e in J(settings, "library")["decks"] if e["id"] == "old3")["name"] == "My own name"


def test_merge_only_without_decisions_file(settings):
    data = mini_backup()
    write_backup(settings.import_dir, "drill-backup-1.json", data)
    rep = run_import(settings)
    assert J(settings, "library") == data["library"]
    assert "none applied" in "\n".join(rep.lines)


def test_forbidden_concepts_stop_the_import_before_writing(settings):
    data = mini_backup(new_extra_concepts=[concept("n9", "outcome a")])
    write_backup(settings.import_dir, "drill-backup-1.json", data)
    settings.decisions_file.write_text(json.dumps(DECISIONS), encoding="utf-8")
    with pytest.raises(ImportError_, match="must not happen"):
        run_import(settings)
    assert not settings.db_path.exists()


def test_broken_decision_writes_nothing_at_all(settings, setup):
    bad = json.loads(json.dumps(DECISIONS))
    bad["decisions"][4]["concept_names"] = SHARED + ["Not There"]
    settings.decisions_file.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ImportError_, match="Not There"):
        run_import(settings)
    assert not settings.db_path.exists()          # planned in memory first: no partial import


def test_pending_decision_on_existing_data_needs_confirmation(settings, setup):
    # merge only first (no decisions file yet), then the decisions arrive
    settings.decisions_file.rename(settings.decisions_file.with_suffix(".off"))
    run_import(settings)
    settings.decisions_file.with_suffix(".off").rename(settings.decisions_file)
    before = kv_full(settings)
    with pytest.raises(ConfirmationRequired) as e:
        run_import(settings)
    plan = "\n".join(e.value.plan)
    assert "Decisions to apply now (once only): old-rename, archive-folder, old-archive, carry" in plan
    assert "CHANGE deck:old3" in plan and "name: \"Unit 3\" -> \"Unit 3 (old build)\"" in plan
    assert "folder added: 'Archive' (f-archive), at the end" in plan
    assert "carried over from old3/o1: higher box" in plan
    assert kv_full(settings) == before
    rep = run_import(settings, confirm=lambda r: True)
    assert rep.changed_keys == ["deck:old3", "prog:new3", "library"]
    assert J(settings, "deck:old3")["name"] == "Unit 3 (old build)"


def test_carry_over_record_count_guard(settings, setup):
    bad = json.loads(json.dumps(DECISIONS))
    bad["decisions"][4]["expect_to_records"] = 23
    settings.decisions_file.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ImportError_, match="expected 23"):
        run_import(settings)
