"""The importer: verbatim first import, plan + confirmation, merge rules, further-along,
idempotency, file safety. Synthetic data only."""
from __future__ import annotations

import hashlib
import json
import os
import stat

import pytest
from conftest import history, kv, kv_full
from server import importer
from server.importer import (ConfirmationRequired, ImportCancelled, ImportError_, merge_deck,
                             norm, run_import)
from server.instance_lock import InstanceLock
from synth import FOLDERS, backup, concept, deck, dumps, prog, rec, simple_backup, write_backup


def YES(rep):
    return True


def NO(rep):
    return False


def imp(settings):
    """Import, agreeing to any change of existing data (the CLI's --yes)."""
    return run_import(settings, confirm=YES)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def J(settings, key):
    v = kv(settings).get(key)
    return None if v is None else json.loads(v)


def pre_import_snaps(settings):
    return sorted(settings.backups_dir.glob("drill-*-pre-import.db")) \
        if settings.backups_dir.exists() else []


# ---- ports of the legacy helpers ---------------------------------------------------------

def test_norm_matches_legacy():
    assert norm("Mostly Harmles") == "mostlyharmles"
    assert norm("  O(n log n) — Big-O ") == "onlognbigo"
    assert norm(None) == "" and norm("") == "" and norm("ÉCOLE 2") == "cole2"


def test_merge_deck_port():
    mine = deck("d", "Mine", [concept("a", "Alpha"), concept("b", "Beta")])
    theirs = deck("d", "Theirs", [concept("x", "ALPHA!"), concept("c", "Gamma"),
                                  concept("b", "Renamed but same id")],
                  coverage={"pages": 3}, source="txt")
    mine["context"] = None
    out = merge_deck(mine, theirs)
    # theirs has more concepts (3 > 2) -> base; mine's Alpha matches by norm(name), Beta by id
    assert [c["id"] for c in out["concepts"]] == ["x", "c", "b"]
    assert out["name"] == "Theirs"                  # the pure port; the importer keeps "Mine"
    assert out["context"] is None                   # present-but-null filled from other
    tie = merge_deck(deck("d", "DB", [concept("a", "A")]), deck("d", "File", [concept("z", "Z")]))
    assert tie["name"] == "DB" and [c["id"] for c in tie["concepts"]] == ["a", "z"]
    a = {"id": "d", "concepts": [concept("a", "A"), concept("b", "B")]}
    b = {"id": "d", "concepts": [], "cards": [], "units": [{"id": "u"}], "source": "s"}
    out = merge_deck(a, b)
    assert out["cards"] == [] and out["units"] == [{"id": "u"}] and out["source"] == "s"
    assert merge_deck(None, b) is b and merge_deck(a, None) is a


# ---- first import, verbatim; second import = no change ----------------------------------

def test_first_import_is_verbatim_needs_no_confirmation_and_second_changes_nothing(settings):
    data = simple_backup()
    f = write_backup(settings.import_dir, "drill-backup-01.json", data)
    rep = run_import(settings, confirm=None)           # only adds: no confirmation needed
    store = kv(settings)
    assert store["library"] == dumps(data["library"])
    assert store["deck:d1"] == dumps(data["decks"]["d1"])
    assert store["deck:d2"] == dumps(data["decks"]["d2"])
    assert store["prog:d1"] == dumps(data["prog"]["d1"])
    assert "prog:d2" not in store                   # prog null in Drill = no key
    assert store["prefs"] == dumps(data["prefs"])
    assert rep.kv_writes == 5 and rep.history_rows == 0 and rep.changed_keys == []
    assert history(settings) == []
    before = kv_full(settings)

    rep2 = run_import(settings, confirm=None)
    assert rep2.kv_writes == 0 and rep2.history_rows == 0
    assert kv_full(settings) == before                # values AND updated_at untouched
    assert set(rep2.key_status.values()) == {"unchanged"}
    text = "\n".join(rep2.lines)
    assert "Summary: 0 kv writes, 0 kv_history rows added" in text
    assert "No snapshot taken" in text
    assert f"sha256={sha(f)}" in text


def test_no_op_run_makes_no_snapshot_and_no_write(settings):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    run_import(settings, confirm=None)
    assert pre_import_snaps(settings) == []           # there was no database to snapshot
    mtime = settings.db_path.stat().st_mtime_ns
    for _ in range(2):
        rep = run_import(settings, confirm=NO)        # would refuse if asked; must not be asked
        assert rep.snapshot is None and rep.kv_writes == 0
    assert pre_import_snaps(settings) == []
    assert settings.db_path.stat().st_mtime_ns == mtime


def _second_file_changing_d1(settings):
    changed = simple_backup(exported="2026-09-05T00:00:00.000Z")
    changed["decks"]["d1"]["concepts"].append(concept("c9", "Doohickey"))
    write_backup(settings.import_dir, "drill-backup-2.json", changed)


def test_change_to_existing_key_needs_confirmation(settings):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    run_import(settings, confirm=None)
    _second_file_changing_d1(settings)
    before = kv_full(settings)
    with pytest.raises(ConfirmationRequired) as e:
        run_import(settings, confirm=None)
    plan = "\n".join(e.value.plan)
    assert "CHANGE deck:d1" in plan and "concepts added (1): 'Doohickey'" in plan
    assert "deck entry d1 ('Deck One'): nCon 2 -> 3" in plan
    assert kv_full(settings) == before and pre_import_snaps(settings) == []
    with pytest.raises(ImportCancelled):
        run_import(settings, confirm=NO)
    assert kv_full(settings) == before and pre_import_snaps(settings) == []
    asked = []
    rep = run_import(settings, confirm=lambda r: asked.append("\n".join(r.lines)) or True)
    assert asked and "CHANGE deck:d1" in asked[0]
    assert [c["id"] for c in J(settings, "deck:d1")["concepts"]][-1] == "c9"
    assert rep.changed_keys == ["deck:d1", "library"]
    assert len(pre_import_snaps(settings)) == 1
    assert history(settings, "deck:d1") == [before_value(before, "deck:d1")]


def before_value(rows, key):
    return next(v for k, v, _ in rows if k == key)


def test_adding_new_keys_to_existing_db_needs_no_confirmation(settings):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    run_import(settings, confirm=None)
    d3 = deck("d3", "Deck Three", [concept("c7", "Thingamajig")])
    other = backup(FOLDERS, [(d3, "f-a")], exported="2026-09-06T00:00:00.000Z",
                   entries=None)
    other["prefs"] = None
    write_backup(settings.import_dir, "drill-backup-2.json", other)
    # the library lists the new deck, so `library` changes: that is an existing key
    with pytest.raises(ConfirmationRequired):
        run_import(settings, confirm=None)
    # an exam draft for an existing deck is a new key only
    write_backup(settings.import_dir, "drill-backup-2.json",
                 simple_backup(exported="2026-09-06T00:00:00.000Z", exams={"d1": {"p": 1}}))
    rep = run_import(settings, confirm=None)
    assert rep.added_keys == ["exam:d1"] and rep.changed_keys == []
    assert len(pre_import_snaps(settings)) == 1       # something was written -> snapshot


def test_cli_refuses_without_yes_and_proceeds_with_yes(settings, capsys, monkeypatch):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    assert importer.main([]) == 0
    _second_file_changing_d1(settings)
    before = kv_full(settings)
    for answer in ["no", "", "y", "YES"]:
        monkeypatch.setattr("builtins.input", lambda _: answer)
        assert importer.main([]) == 1
        assert kv_full(settings) == before
    out = capsys.readouterr().out
    assert "CHANGE deck:d1" in out and "IMPORT CANCELLED" in out
    assert pre_import_snaps(settings) == []

    def eof(_):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)            # no terminal: treated as "no"
    assert importer.main([]) == 1 and kv_full(settings) == before

    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("--yes must not ask"))
    assert importer.main(["--yes"]) == 0
    assert "--yes given" in capsys.readouterr().out
    assert len(J(settings, "deck:d1")["concepts"]) == 3
    assert len(pre_import_snaps(settings)) == 1


def test_cli_typed_yes_proceeds(settings, monkeypatch):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    assert importer.main([]) == 0
    _second_file_changing_d1(settings)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert importer.main([]) == 0
    assert len(J(settings, "deck:d1")["concepts"]) == 3


def test_import_files_are_never_modified(settings):
    f1 = write_backup(settings.import_dir, "drill-backup-a.json", simple_backup())
    f2 = write_backup(settings.import_dir, "drill-backup-b.json",
                      simple_backup(exported="2026-09-02T00:00:00.000Z"))
    other = settings.import_dir / "INVENTORY.md"
    other.write_text("inventory", encoding="utf-8")
    before = {p: (sha(p), p.stat().st_mtime_ns) for p in (f1, f2, other)}
    for p in (f1, f2, other):                       # read-only: the importer can't write them
        os.chmod(p, stat.S_IREAD)
    try:
        rep = imp(settings)
        imp(settings)
    finally:
        for p in (f1, f2, other):
            os.chmod(p, stat.S_IREAD | stat.S_IWRITE)
    assert {p: (sha(p), p.stat().st_mtime_ns) for p in (f1, f2, other)} == before
    assert sorted(os.listdir(settings.import_dir)) == sorted(
        ["drill-backup-a.json", "drill-backup-b.json", "INVENTORY.md"])
    text = "\n".join(rep.lines)
    assert text.count("... OK") == 2 and "CHANGED!" not in text


def test_only_matching_files_are_read(settings):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    (settings.import_dir / "other.json").write_text("{not json", encoding="utf-8")
    (settings.import_dir / "drill-backup-1.json.bak").write_text("{bad", encoding="utf-8")
    imp(settings)
    assert "deck:d1" in kv(settings)


def test_no_files_or_bad_file_stops_without_writing(settings):
    with pytest.raises(ImportError_, match="No drill-backup"):
        imp(settings)
    (settings.import_dir / "drill-backup-x.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(ImportError_, match="not valid"):
        imp(settings)
    assert not settings.db_path.exists()


def test_unknown_top_level_key_stops_without_writing(settings):
    data = simple_backup()
    data["mystery"] = {"x": 1}
    write_backup(settings.import_dir, "drill-backup-1.json", data)
    with pytest.raises(ImportError_, match="unknown top-level"):
        imp(settings)
    assert not settings.db_path.exists()


def test_unknown_inner_keys_are_kept(settings):
    data = simple_backup()
    data["decks"]["d1"]["concepts"][0]["weird"] = {"nested": [1, "✓"]}
    data["decks"]["d1"]["futureField"] = 7
    data["library"]["decks"][0]["kind2"] = "x"
    data["prog"]["d1"]["m"]["c1"]["newStat"] = 3
    write_backup(settings.import_dir, "drill-backup-1.json", data)
    imp(settings)
    assert J(settings, "deck:d1") == data["decks"]["d1"]
    assert J(settings, "library") == data["library"]
    assert J(settings, "prog:d1") == data["prog"]["d1"]


# ---- two files, same deck -------------------------------------------------------------

def test_two_files_same_deck_no_concept_missing(settings):
    old = deck("d1", "Deck", [concept("c1", "Widget"), concept("c2", "Gadget"),
                              concept("c9", "Only old")], source="pasted")
    new = deck("d1", "Deck", [concept("c1", "Widget v2"), concept("n2", "gadget"),
                              concept("c3", "Sprocket"), concept("c4", "Cog")],
               coverage={"found": 4})
    b1 = backup(FOLDERS, [(old, "f-a")], exported="2026-09-01T00:00:00.000Z")
    b2 = backup(FOLDERS, [(new, "f-a")], exported="2026-09-05T00:00:00.000Z")
    write_backup(settings.import_dir, "drill-backup-new.json", b2)
    write_backup(settings.import_dir, "drill-backup-old.json", b1)
    imp(settings)
    d = J(settings, "deck:d1")
    ids = [c["id"] for c in d["concepts"]]
    # base = the fuller copy (new, 4 > 3); old's c1 matches by id, c2 by name "gadget"
    assert ids == ["c1", "n2", "c3", "c4", "c9"]
    for c in old["concepts"] + new["concepts"]:
        assert any(x["id"] == c["id"] or norm(x["name"]) == norm(c["name"]) for x in d["concepts"])
    assert {k["id"] for k in d["cards"]} >= {"k-" + c["id"] for c in old["concepts"] + new["concepts"]}
    assert d["coverage"] == {"found": 4} and d["source"] == "pasted"
    e = J(settings, "library")["decks"][0]
    assert (e["nCon"], e["nQ"]) == (5, 10)          # recomputed like the app does
    assert run_import(settings, confirm=None).kv_writes == 0


def test_files_processed_oldest_exported_first(settings):
    a = deck("d1", "From A", [concept("c1", "One")])
    b = deck("d1", "From B", [concept("c2", "Two")])
    write_backup(settings.import_dir, "drill-backup-1.json",
                 backup(FOLDERS, [(a, "f-a")], exported="2026-09-09T00:00:00.000Z"))
    write_backup(settings.import_dir, "drill-backup-2.json",
                 backup(FOLDERS, [(b, "f-a")], exported="2026-09-01T00:00:00.000Z"))
    rep = imp(settings)
    assert J(settings, "deck:d1")["name"] == "From B"
    assert [c["id"] for c in J(settings, "deck:d1")["concepts"]] == ["c2", "c1"]
    assert rep.lines[1].strip().startswith("drill-backup-2.json")


def test_existing_deck_name_is_never_changed_by_a_fuller_file_copy(settings, make_client):
    d1 = deck("d1", "Original", [concept("c1", "A")])
    write_backup(settings.import_dir, "drill-backup-1.json",
                 backup(FOLDERS, [(d1, "f-a")], exported="2026-09-01T00:00:00.000Z"))
    imp(settings)
    # Elisha renames the deck in the app: library entry and deck.name
    with make_client() as c:
        lib = J(settings, "library")
        lib["decks"][0]["name"] = "My Rename"
        dk = J(settings, "deck:d1")
        dk["name"] = "My Rename"
        c.put("/api/store/library", content=dumps(lib).encode("utf-8"))
        c.put("/api/store/deck%3Ad1", content=dumps(dk).encode("utf-8"))
    fuller = deck("d1", "Original", [concept("c1", "A"), concept("c2", "B"), concept("c3", "C")])
    write_backup(settings.import_dir, "drill-backup-2.json",
                 backup(FOLDERS, [(fuller, "f-a")], exported="2026-09-02T00:00:00.000Z"))
    rep = imp(settings)
    d = J(settings, "deck:d1")
    assert d["name"] == "My Rename" and len(d["concepts"]) == 3   # file copy was the base
    assert J(settings, "library")["decks"][0]["name"] == "My Rename"
    assert "name:" not in "\n".join(rep.plan)


# ---- library ----------------------------------------------------------------------------

def test_library_order_colours_and_names_kept(settings, make_client):
    d1 = deck("d1", "One", [concept("c1", "A")])
    d2 = deck("d2", "Two", [concept("c2", "B")])
    write_backup(settings.import_dir, "drill-backup-1.json",
                 backup(FOLDERS, [(d1, "f-a"), (d2, "f-b")], exported="2026-09-01T00:00:00.000Z"))
    imp(settings)
    lib = J(settings, "library")
    lib["decks"][0]["name"] = "One (renamed)"
    lib["decks"][0]["folderId"] = "f-b"
    with make_client() as c:
        c.put("/api/store/library", content=dumps(lib).encode("utf-8"))
    d3 = deck("d3", "Three", [concept("c3", "C")])
    folders2 = [{"id": "f-new", "name": "New", "color": "#abcdef"},
                {"id": "f-b", "name": "Beta renamed", "color": "#000000"}]
    write_backup(settings.import_dir, "drill-backup-2.json",
                 backup(folders2, [(d1, "f-a"), (d3, "f-new")], exported="2026-09-02T00:00:00.000Z"))
    imp(settings)
    lib = J(settings, "library")
    assert lib["folders"] == FOLDERS + [folders2[0]]         # order + colours kept, none removed
    assert [e["id"] for e in lib["decks"]] == ["d1", "d2", "d3"]
    assert lib["decks"][0]["name"] == "One (renamed)" and lib["decks"][0]["folderId"] == "f-b"


def test_new_deck_with_unknown_folder_goes_to_restored(settings):
    d1 = deck("d1", "One", [concept("c1", "A")])
    write_backup(settings.import_dir, "drill-backup-1.json", backup(FOLDERS, [(d1, "f-gone")]))
    imp(settings)
    lib = J(settings, "library")
    assert lib["folders"][-1] == {"id": "f-restored", "name": "Restored"}
    assert lib["decks"][0]["folderId"] == "f-restored"


def test_deck_without_content_is_skipped_and_reported(settings):
    data = simple_backup()
    data["decks"]["d2"] = None
    write_backup(settings.import_dir, "drill-backup-1.json", data)
    rep = imp(settings)
    assert rep.skipped == [("drill-backup-1.json", "d2", "Deck Two")]
    assert [e["id"] for e in J(settings, "library")["decks"]] == ["d1"]


def test_skill_deck_badge():
    units = [{"id": "u1", "practice": [1, 2, 3]}]
    sk = {"id": "s", "name": "Calc", "kind": "skill", "concepts": [], "units": units}
    e = {"id": "s", "name": "Calc", "folderId": "f-a", "created": 1, "kind": "skill",
         "nCon": 1, "nQ": 3}
    assert importer.badge_counts(e, sk) == (1, 3)


# ---- progress ---------------------------------------------------------------------------

def _two_file_prog(settings, db_deck_n, file_deck_n, db_rec, file_rec, db_asked=5, file_asked=5,
                   db_extra=None, file_extra=None):
    """Import file A (database copy), then file B, both for deck d1 / concept c1."""
    ca = [concept("c1", "Shared")] + [concept(f"a{i}", f"A{i}") for i in range(db_deck_n - 1)]
    cb = [concept("c1", "Shared")] + [concept(f"b{i}", f"B{i}") for i in range(file_deck_n - 1)]
    pa = prog({"c1": db_rec}, asked=db_asked, **(db_extra or {}))
    pb = prog({"c1": file_rec}, asked=file_asked, **(file_extra or {}))
    write_backup(settings.import_dir, "drill-backup-1.json",
                 backup(FOLDERS, [(deck("d1", "D", ca), "f-a")], progs={"d1": pa},
                        exported="2026-09-01T00:00:00.000Z"))
    imp(settings)
    write_backup(settings.import_dir, "drill-backup-2.json",
                 backup(FOLDERS, [(deck("d1", "D", cb), "f-a")], progs={"d1": pb},
                        exported="2026-09-02T00:00:00.000Z"))
    rep = imp(settings)
    return J(settings, "prog:d1"), rep


@pytest.mark.parametrize("db_rec,file_rec,winner", [
    (rec(box=2, right=1), rec(box=3, right=0), "file"),                    # 1. higher box
    (rec(box=4, right=0), rec(box=3, right=9), "db"),
    (rec(box=2, right=5), rec(box=2, right=6), "file"),                    # 2. more right
    (rec(box=2, right=7), rec(box=2, right=6), "db"),
    (rec(box=2, right=5, due=100), rec(box=2, right=5, due=200), "file"),  # 3. later due
    (rec(box=2, right=5, due=300), rec(box=2, right=5, due=200), "db"),
])
def test_further_along_box_right_due(settings, db_rec, file_rec, winner):
    p, _ = _two_file_prog(settings, 2, 2, db_rec, file_rec)
    assert p["m"]["c1"] == (file_rec if winner == "file" else db_rec)


def test_replaced_record_is_named_in_the_plan(settings):
    _, rep = _two_file_prog(settings, 2, 2, rec(box=2, right=1), rec(box=3, right=0))
    plan = "\n".join(rep.plan)
    assert "CHANGE prog:d1" in plan
    assert "record c1: [box=2 right=1 due=1000] -> [box=3 right=0 due=1000] " \
           "(file record: higher box)" in plan


def test_further_along_fuller_copy_breaks_full_tie(settings):
    db_rec = rec(box=2, right=5, due=100, seen=1)
    file_rec = rec(box=2, right=5, due=100, seen=9)
    p, rep = _two_file_prog(settings, 2, 3, db_rec, file_rec)     # file copy is fuller
    assert p["m"]["c1"] == file_rec and rep.undecided == []


def test_further_along_fuller_db_copy_kept(settings):
    db_rec = rec(box=2, right=5, due=100, seen=1)
    file_rec = rec(box=2, right=5, due=100, seen=9)
    p, rep = _two_file_prog(settings, 3, 2, db_rec, file_rec)
    assert p["m"]["c1"] == db_rec and rep.undecided == []


def test_undecided_keeps_database_record_and_reports(settings):
    db_rec = rec(box=2, right=5, due=100, seen=1)
    file_rec = rec(box=2, right=5, due=100, seen=9)
    p, rep = _two_file_prog(settings, 2, 2, db_rec, file_rec)
    assert p["m"]["c1"] == db_rec
    assert rep.undecided == [("d1", "c1")]
    assert "UNDECIDED" in "\n".join(rep.lines)


def test_record_without_box_is_compared_as_the_app_migrates_it(settings):
    # legacy migrate(): no box -> box = done ? 2 : 0. A "done" record without box beats box 1.
    old_style = {"run": 3, "right": 3, "wrong": 1, "done": True}
    p, rep = _two_file_prog(settings, 2, 2, rec(box=1, right=9, due=5), old_style)
    assert p["m"]["c1"] == old_style                   # stored verbatim: no box added
    assert "box" not in p["m"]["c1"]
    # not done -> box 0: loses to box 1 even with more right answers
    p2 = importer.further_along(rec(box=1, right=0), {"right": 50, "wrong": 0, "done": False},
                                2, 2, now_ms=0)
    assert p2 == ("a", "higher box")
    # both without box, both done: box 2 = 2, right decides
    assert importer.further_along({"right": 1, "done": True}, {"right": 2, "done": True},
                                  2, 2, now_ms=0) == ("b", "more right answers")


def test_record_only_on_one_side_is_kept(settings):
    ca = [concept("c1", "One"), concept("c2", "Two")]
    write_backup(settings.import_dir, "drill-backup-1.json",
                 backup(FOLDERS, [(deck("d1", "D", ca), "f-a")],
                        progs={"d1": prog({"c1": rec(box=1)})}, exported="2026-09-01T00:00:00.000Z"))
    write_backup(settings.import_dir, "drill-backup-2.json",
                 backup(FOLDERS, [(deck("d1", "D", ca), "f-a")],
                        progs={"d1": prog({"c2": rec(box=4)})}, exported="2026-09-02T00:00:00.000Z"))
    imp(settings)
    assert J(settings, "prog:d1")["m"] == {"c1": rec(box=1), "c2": rec(box=4)}


@pytest.mark.parametrize("bad_m", [None, [], "x", 5, {"c1": [1, 2]}])
def test_unexpected_prog_shape_in_db_stops_and_writes_nothing(settings, make_client, bad_m):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    imp(settings)
    p = J(settings, "prog:d1")
    p["m"] = bad_m
    with make_client() as c:
        c.put("/api/store/prog%3Ad1", content=dumps(p).encode("utf-8"))
    before = kv_full(settings)
    write_backup(settings.import_dir, "drill-backup-2.json",
                 simple_backup(exported="2026-09-02T00:00:00.000Z"))
    with pytest.raises(ImportError_, match="prog:d1"):
        imp(settings)
    assert kv_full(settings) == before and pre_import_snaps(settings) == []


def test_prog_that_is_not_an_object_stops(settings, make_client):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    imp(settings)
    with make_client() as c:
        c.put("/api/store/prog%3Ad1", content=b"[1,2]")
    with pytest.raises(ImportError_, match="not an object"):
        imp(settings)


def test_file_m_is_never_dropped_when_db_has_no_m(settings, make_client):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    imp(settings)
    p = J(settings, "prog:d1")
    del p["m"]
    with make_client() as c:
        c.put("/api/store/prog%3Ad1", content=dumps(p).encode("utf-8"))
    imp(settings)
    assert J(settings, "prog:d1")["m"] == simple_backup()["prog"]["d1"]["m"]


def test_deck_level_prog_rule(settings):
    p, _ = _two_file_prog(settings, 2, 2, rec(box=5), rec(box=1), db_asked=10, file_asked=20,
                          db_extra={"teach": {"passed": {"T#0": True}}, "onlyDb": 1},
                          file_extra={"teach": {"passed": {}}, "course": {"passed": {"u": 1}}})
    assert p["asked"] == 20 and p["teach"] == {"passed": {}}
    assert p["onlyDb"] == 1 and p["course"] == {"passed": {"u": 1}}
    assert p["m"]["c1"] == rec(box=5)


def test_deck_level_prog_tie_keeps_database(settings):
    p, _ = _two_file_prog(settings, 2, 2, rec(), rec(), db_asked=7, file_asked=7,
                          db_extra={"sessions": 1}, file_extra={"sessions": 99})
    assert p["sessions"] == 1


# ---- prefs and exams --------------------------------------------------------------------

def test_prefs_from_newest_v2_only_if_none(settings):
    write_backup(settings.import_dir, "drill-backup-1.json",
                 simple_backup(exported="2026-09-01T00:00:00.000Z", prefs={"n": "old"}))
    write_backup(settings.import_dir, "drill-backup-2.json",
                 simple_backup(exported="2026-09-03T00:00:00.000Z", prefs={"n": "newest"}))
    write_backup(settings.import_dir, "drill-backup-3.json",
                 simple_backup(exported="2026-09-09T00:00:00.000Z", v=1))
    imp(settings)
    assert J(settings, "prefs") == {"n": "newest"}
    write_backup(settings.import_dir, "drill-backup-4.json",
                 simple_backup(exported="2026-09-10T00:00:00.000Z", prefs={"n": "later"}))
    imp(settings)
    assert J(settings, "prefs") == {"n": "newest"}      # settings in use are never overwritten


def test_exam_only_if_missing(settings):
    write_backup(settings.import_dir, "drill-backup-1.json",
                 simple_backup(exams={"d1": {"paper": "first"}}))
    imp(settings)
    write_backup(settings.import_dir, "drill-backup-2.json",
                 simple_backup(exported="2026-09-05T00:00:00.000Z",
                               exams={"d1": {"paper": "second"}, "d2": {"paper": "x"}}))
    imp(settings)
    assert J(settings, "exam:d1") == {"paper": "first"}
    assert J(settings, "exam:d2") == {"paper": "x"}


# ---- CLI lock; API ------------------------------------------------------------------------

def test_cli_refuses_while_server_holds_lock(settings, capsys):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    with InstanceLock(settings.lock_file, "server"):
        assert importer.main([]) == 2
    assert "IMPORT STOPPED" in capsys.readouterr().out
    assert not settings.db_path.exists()
    assert importer.main([]) == 0
    assert "Per deck" in capsys.readouterr().out


def test_import_endpoint_adds_then_is_a_no_op(client, settings):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    r = client.post("/api/import")
    assert r.status_code == 200 and r.json()["kv_writes"] == 5
    r2 = client.post("/api/import")
    assert r2.json()["kv_writes"] == 0 and r2.json()["history_rows"] == 0
    assert r2.json()["snapshot"] is None
    assert client.get("/api/store/deck%3Ad1").json()["name"] == "Deck One"


def test_import_endpoint_409_when_existing_key_would_change(client, settings):
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    assert client.post("/api/import").status_code == 200
    _second_file_changing_d1(settings)
    before = kv_full(settings)
    snaps = pre_import_snaps(settings)     # the server made drill.db at start, so the first
    r = client.post("/api/import")         # import (adds only) took one; the 409 adds none
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "confirmation_required"
    assert "python -m server.importer" in body["message"]
    assert any("CHANGE deck:d1" in line for line in body["plan"])
    assert kv_full(settings) == before and pre_import_snaps(settings) == snaps


def test_import_endpoint_reports_stop(client, settings):
    r = client.post("/api/import")
    assert r.status_code == 409 and r.json()["error"] == "import_stopped"
