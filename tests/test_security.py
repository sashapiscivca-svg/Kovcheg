import json
import os
import shutil
import stat

import pytest
from build_helpers import ENC, make_settings, write_sources

pytest.importorskip("cryptography")

from kovcheg.builder import build_module  # noqa: E402
from kovcheg.security import CACHE_NAME, key_id_of, keygen, sign_module, trusted_keys, verify_module  # noqa: E402


@pytest.fixture
def signed(tmp_path):
    s = make_settings(tmp_path)
    info = keygen(s.keys_dir)
    rep = build_module(s, "m", write_sources(tmp_path / "src"), encoder=ENC)
    return s, info, rep.path


def test_keygen_files_and_overwrite(tmp_path):
    info = keygen(tmp_path / "k")
    if os.name != "nt":   # POSIX permissions; on Windows the file inherits the folder ACL
        assert stat.S_IMODE(os.stat(info.private_path).st_mode) == 0o600
    assert b"PRIVATE KEY" in info.private_path.read_bytes() and b"PUBLIC KEY" in info.public_path.read_bytes()
    assert len(info.key_id) == 16
    with pytest.raises(FileExistsError):
        keygen(tmp_path / "k")
    assert keygen(tmp_path / "k", force=True).key_id != info.key_id
    if os.name != "nt":   # POSIX permissions; on Windows the file inherits the folder ACL
        assert stat.S_IMODE(os.stat(info.private_path).st_mode) == 0o600
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    new = keygen(tmp_path / "k", force=True)
    assert list(trusted_keys(tmp_path / "k")) == [key_id_of(load_pem_public_key(new.public_path.read_bytes()))] == [new.key_id]


def test_valid_and_cache(signed):
    s, info, path = signed
    v = verify_module(path, s.keys_dir)
    assert (v.status, v.key_id) == ("valid", info.key_id) and v.ok
    v = verify_module(path, s.keys_dir, deep=True)
    assert v.status == "valid" and "cached" not in v.message and (path / CACHE_NAME).exists()
    v = verify_module(path, s.keys_dir, deep=True)
    assert v.status == "valid" and "cached" in v.message


def _flip_byte(p, offset=-10):
    data = bytearray(p.read_bytes())
    data[offset] ^= 0xFF
    st = p.stat()
    p.write_bytes(bytes(data))
    return st


@pytest.mark.parametrize("name", ["kovcheg.db", "dense.f16.npy", "sparse.npz"])
def test_deep_detects_modification(signed, name):
    s, _, path = signed
    assert verify_module(path, s.keys_dir, deep=True).status == "valid"     # populates the cache
    _flip_byte(path / name)
    assert verify_module(path, s.keys_dir).status == "valid"                # shallow: same size, not detected
    v = verify_module(path, s.keys_dir, deep=True)
    assert v.status == "invalid" and name in v.message


def test_cache_not_fooled_by_restored_mtime(signed):
    s, _, path = signed
    verify_module(path, s.keys_dir, deep=True)
    p = path / "dense.f16.npy"
    st = _flip_byte(p, 200)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))   # 1 ms: above every filesystem's timestamp resolution
    assert verify_module(path, s.keys_dir, deep=True).status == "invalid"


def test_size_change_and_missing(signed):
    s, _, path = signed
    with open(path / "sparse.npz", "ab") as f:
        f.write(b"x")
    assert verify_module(path, s.keys_dir).status == "invalid"
    (path / "sparse.npz").unlink()
    v = verify_module(path, s.keys_dir)
    assert v.status == "missing_files" and "sparse.npz" in v.message
    (path / "manifest.json").unlink()
    assert verify_module(path, s.keys_dir).status == "missing_files"


def test_tampered_manifest_and_untrusted(signed, tmp_path):
    s, info, path = signed
    mf = json.loads((path / "manifest.json").read_text())
    mf["description"] = "evil"
    (path / "manifest.json").write_text(json.dumps(mf))
    assert verify_module(path, s.keys_dir).status == "invalid"
    sign_module(path, s.keys_dir)
    assert verify_module(path, s.keys_dir).status == "valid"
    other = tmp_path / "other_keys"
    keygen(other)
    v = verify_module(path, other)
    assert v.status == "untrusted" and v.key_id == info.key_id
    assert verify_module(path, None).status == "untrusted"
    # trusting it via keys/trusted/
    (other / "trusted").mkdir()
    shutil.copy(info.public_path, other / "trusted" / "friend.pem")
    assert verify_module(path, other).status == "valid"


def test_corrupt_signature_and_manifest(signed):
    s, _, path = signed
    (path / "manifest.sig").write_bytes(b"short")
    assert verify_module(path, s.keys_dir).status == "invalid"
    (path / "manifest.json").write_text("{not json")
    assert verify_module(path, s.keys_dir).status == "error"


def test_unsigned_module(tmp_path):
    s = make_settings(tmp_path)
    rep = build_module(s, "u", write_sources(tmp_path / "src"), encoder=None)
    v = verify_module(rep.path, s.keys_dir, deep=True)
    assert v.status == "unsigned" and v.ok and "intact" in v.message
    _flip_byte(rep.path / "kovcheg.db", 100)
    assert verify_module(rep.path, s.keys_dir, deep=True).status == "invalid"
    with pytest.raises(FileNotFoundError):
        sign_module(rep.path, s.keys_dir)


def test_untrusted_signature_still_detects_modified_files(signed, tmp_path):
    """A module signed by an unknown key must still be reported INVALID when its files were changed."""
    s, _, path = signed
    other = tmp_path / "stranger_keys"
    keygen(other)
    assert verify_module(path, other, deep=True).status == "untrusted"
    _flip_byte(path / "kovcheg.db")
    assert verify_module(path, other, deep=True, use_cache=False).status == "invalid"


def test_use_cache_false_rehashes(signed):
    s, _, path = signed
    assert verify_module(path, s.keys_dir, deep=True).status == "valid"
    st = _flip_byte(path / "dense.f16.npy")
    os.utime(path / "dense.f16.npy", ns=(st.st_atime_ns, st.st_mtime_ns))    # attacker restores size and mtime
    assert verify_module(path, s.keys_dir, deep=True, use_cache=False).status == "invalid"
