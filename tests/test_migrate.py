import json
import sqlite3

import numpy as np
import pytest

from kovcheg.migrate import migrate_module
from kovcheg.store import ModuleIndex

DIM = 16


def _vec(seed):
    v = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def make_v1(folder, rows):
    folder.mkdir(parents=True)
    con = sqlite3.connect(folder / "search_bge.db")
    con.execute("""CREATE TABLE docs (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, content TEXT NOT NULL,
                   dense_vec BLOB NOT NULL, sparse_vec TEXT, chunk_idx INTEGER, total_chunks INTEGER, file_hash TEXT)""")
    con.execute("CREATE TABLE graph_edges (source TEXT, target TEXT, weight INTEGER, PRIMARY KEY (source, target)) WITHOUT ROWID")
    for fn, content, seed, sparse, idx, fh in rows:
        con.execute("INSERT INTO docs (filename, content, dense_vec, sparse_vec, chunk_idx, total_chunks, file_hash) VALUES (?,?,?,?,?,?,?)",
                    (fn, content, _vec(seed).tobytes(), json.dumps(sparse) if sparse is not None else None, idx, 2, fh))
    con.commit()
    con.close()
    (folder / "manifest.json").write_text(json.dumps({"name": folder.name, "description": "old module", "created": "2025-01-01"}))
    (folder / "manifest.sig").write_bytes(b"old signature")


ROWS = [
    ("codes.txt", "Pneumonia is coded J18.9 in ICD-10.", 1, {"100": 0.3, "200": 0.1}, 0, "abc"),
    ("codes.txt", "Bronchitis is coded J20.", 2, {"100": 0.05, "300": 0.2}, 1, "abc"),
    ("Wiki: Water", "Boil water for one minute.", 3, {"400": 0.2, "bad": 1}, 1, None),
    ("Wiki: Water", "Water article intro.", 4, None, 0, None),
    ("Wiki: Water", "Boil water for one minute.", 3, {"400": 0.2}, 1, None),       # duplicate from an old re-run
]


def test_migrate_roundtrip(tmp_path):
    folder = tmp_path / "modules" / "med"
    make_v1(folder, ROWS)
    rep = migrate_module(folder)
    assert (rep.documents, rep.chunks, rep.duplicates_removed, rep.dim) == (2, 4, 1, DIM)
    assert any("1024" in m for m in rep.messages)
    names = {p.name for p in folder.iterdir()}
    assert names == {"kovcheg.db", "dense.f16.npy", "sparse.npz", "manifest.json", "search_bge.db.v1"}
    mf = json.loads((folder / "manifest.json").read_text())
    assert mf["version"] == 2 and mf["encoder"] == {"id": "bge-m3", "dim": DIM, "sparse": True} and mf["description"] == "old module"
    with ModuleIndex.open(folder) as m:
        assert m.encoder_id == "bge-m3" and m.dim == DIM and m.n_chunks == 4
        docs = {d["path"]: d for d in m.documents()}
        assert docs["Wiki: Water"]["title"] == "Water" and docs["Wiki: Water"]["kind"] == "zim"
        assert docs["codes.txt"]["sha256"] == "abc" and docs["codes.txt"]["title"] == "codes"
        cid = m.bm25("J18.9", 1)[0][0]
        ch = m.chunks([cid])[0]
        assert ch.text.startswith("Pneumonia") and ch.page is None and ch.section is None
        # ordering by chunk_idx, then dense row maps to the original vector
        water = [c.text for c in sorted(m.chunks(m.row_chunk_ids()), key=lambda c: (c.doc_id, c.idx)) if c.doc_path == "Wiki: Water"]
        assert water == ["Water article intro.", "Boil water for one minute."]
        rows = m.row_chunk_ids()
        d = m.dense().astype(np.float32)
        i = int(np.where(rows == cid)[0][0])
        assert np.allclose(d[i], _vec(1), atol=2e-3)
        assert int(rows[int(np.argmax(d @ _vec(2)))]) == m.bm25("Bronchitis", 1)[0][0]
        sp = m.sparse_postings()
        c100, w100 = sp.lookup(100)
        assert len(c100) == 2 and np.isclose(float(w100[list(c100).index(cid)]), 0.3, atol=1e-3)
        assert sp.lookup(400)[0].size == 1


def test_migrate_delete_old_and_refusals(tmp_path):
    folder = tmp_path / "m"
    make_v1(folder, ROWS[:2])
    migrate_module(folder, delete_old=True)
    assert not (folder / "search_bge.db").exists() and not (folder / "search_bge.db.v1").exists()
    with pytest.raises(FileNotFoundError):
        migrate_module(folder)
    other = tmp_path / "o"
    make_v1(other, ROWS[:1])
    (other / "kovcheg.db").write_bytes(b"")
    with pytest.raises(FileExistsError):
        migrate_module(other)


def test_migrate_failure_leaves_v1_untouched(tmp_path):
    folder = tmp_path / "bad"
    make_v1(folder, ROWS[:1])
    con = sqlite3.connect(folder / "search_bge.db")
    con.execute("INSERT INTO docs (filename, content, dense_vec) VALUES ('x', 'y', ?)", (np.zeros(3, np.float32).tobytes(),))
    con.commit()
    con.close()
    before = sorted(p.name for p in folder.iterdir())
    with pytest.raises(ValueError):
        migrate_module(folder)
    assert sorted(p.name for p in folder.iterdir()) == before


def test_migrate_signs(tmp_path):
    pytest.importorskip("cryptography")
    from kovcheg.security import keygen, verify_module
    keys = tmp_path / "keys"
    keygen(keys)
    folder = tmp_path / "s"
    make_v1(folder, ROWS)
    rep = migrate_module(folder, keys_dir=keys)
    assert rep.signed_by
    assert verify_module(folder, keys, deep=True).status == "valid"
