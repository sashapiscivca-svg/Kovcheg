"""Module integrity and authenticity: Ed25519 keys (PEM), manifest signing and verification.

`manifest.json` lists sha256 + size of every module file; `manifest.sig` is an Ed25519 signature of the exact bytes of
`manifest.json`. Verification checks the signature against the trusted keys (`keys/*.pem` — public keys, or the public
half of `private_key.pem` — and `keys/trusted/*.pem`), then the files: sizes always, sha256 with `deep=True`.
Deep results are cached in `<module>/.verified.json` keyed by (size, mtime_ns) of every file, so the expensive hashing
runs only after a file changes. `cryptography` is imported lazily (extra "sign").
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .store import MANIFEST_NAME, SIG_NAME, sha256_file, write_json_atomic

PRIVATE_NAME = "private_key.pem"
PUBLIC_NAME = "public_key.pem"
CACHE_NAME = ".verified.json"


@dataclass
class KeyInfo:
    key_id: str
    private_path: Path
    public_path: Path


@dataclass
class Verification:
    status: str                  # valid | invalid | unsigned | untrusted | missing_files | error
    key_id: str | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        """True when nothing is known to be wrong (valid, or unsigned with intact files)."""
        return self.status in ("valid", "unsigned")


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError:
        raise ImportError('signing needs the "sign" extra: pip install "kovcheg[sign]"') from None
    return serialization, ed25519


def key_id_of(public_key) -> str:
    serialization, _ = _crypto()
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def keygen(keys_dir: Path, *, force: bool = False) -> KeyInfo:
    """Create an Ed25519 key pair in keys_dir (private_key.pem mode 0600, public_key.pem). Refuses to overwrite unless force."""
    serialization, ed25519 = _crypto()
    keys_dir = Path(keys_dir)
    keys_dir.mkdir(parents=True, exist_ok=True)
    priv_p, pub_p = keys_dir / PRIVATE_NAME, keys_dir / PUBLIC_NAME
    if not force and (priv_p.exists() or pub_p.exists()):
        raise FileExistsError(f"keys already exist in {keys_dir} (use force to overwrite; modules signed with the old key will become untrusted)")
    key = ed25519.Ed25519PrivateKey.generate()
    priv_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    tmp = priv_p.with_name(PRIVATE_NAME + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(priv_pem)
    os.chmod(tmp, 0o600)
    os.replace(tmp, priv_p)
    pub_p.write_bytes(pub_pem)
    return KeyInfo(key_id_of(key.public_key()), priv_p, pub_p)


def load_private_key(keys_dir: Path):
    serialization, ed25519 = _crypto()
    p = Path(keys_dir) / PRIVATE_NAME
    if not p.exists():
        raise FileNotFoundError(f"no private key {p} (create one with `kovcheg keygen`)")
    key = serialization.load_pem_private_key(p.read_bytes(), password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise ValueError(f"{p} is not an Ed25519 private key")
    return key


def has_private_key(keys_dir: Path | None) -> bool:
    return keys_dir is not None and (Path(keys_dir) / PRIVATE_NAME).is_file()


def trusted_keys(keys_dir: Path | None) -> dict[str, object]:
    """key id -> Ed25519 public key, from keys_dir/*.pem (public keys or the private key's public half) and keys_dir/trusted/*.pem.
    Unreadable or non-Ed25519 files are ignored."""
    if keys_dir is None:
        return {}
    keys_dir = Path(keys_dir)
    serialization, ed25519 = _crypto()
    out: dict[str, object] = {}
    files = sorted(keys_dir.glob("*.pem")) + sorted((keys_dir / "trusted").glob("*.pem"))
    for f in files:
        try:
            data = f.read_bytes()
            if b"PRIVATE KEY" in data:
                k = serialization.load_pem_private_key(data, password=None)
                pub = k.public_key() if isinstance(k, ed25519.Ed25519PrivateKey) else None
            else:
                pub = serialization.load_pem_public_key(data)
            if isinstance(pub, ed25519.Ed25519PublicKey):
                out[key_id_of(pub)] = pub
        except (OSError, ValueError, TypeError):
            continue
    return out


def sign_module(path: Path, keys_dir: Path) -> str:
    """Set manifest 'signer' to this key's id, rewrite manifest.json and write manifest.sig. Returns the key id."""
    path = Path(path)
    key = load_private_key(keys_dir)
    kid = key_id_of(key.public_key())
    mf = path / MANIFEST_NAME
    if not mf.exists():
        raise FileNotFoundError(f"{mf} not found (build the module first)")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    if manifest.get("signer") != kid:
        manifest["signer"] = kid
        write_json_atomic(mf, manifest)
    sig = key.sign(mf.read_bytes())
    tmp = path / (SIG_NAME + ".tmp")
    tmp.write_bytes(sig)
    os.replace(tmp, path / SIG_NAME)
    (path / CACHE_NAME).unlink(missing_ok=True)
    return kid


def _stat_key(p: Path) -> list[int]:
    st = p.stat()
    return [st.st_size, st.st_mtime_ns]


def _cache_matches(path: Path, names: list[str]) -> bool:
    try:
        cache = json.loads((path / CACHE_NAME).read_text(encoding="utf-8"))
        return all(cache.get("files", {}).get(n) == _stat_key(path / n) for n in names) and set(cache.get("files", {})) == set(names)
    except (OSError, ValueError, AttributeError):
        return False


def _cache_store(path: Path, names: list[str]) -> None:
    try:
        write_json_atomic(path / CACHE_NAME, {"files": {n: _stat_key(path / n) for n in names}})
    except OSError:
        pass                     # read-only media: no cache, verification still works


def verify_module(path: Path, keys_dir: Path | None = None, *, deep: bool = False, use_cache: bool = True) -> Verification:
    """Check a module's manifest signature and files. Never raises. `use_cache=False` forces re-hashing in deep mode."""
    path = Path(path)
    try:
        return _verify(path, keys_dir, deep, use_cache)
    except Exception as e:  # noqa: BLE001
        return Verification("error", None, f"verification failed: {e}")


def _verify(path: Path, keys_dir: Path | None, deep: bool, use_cache: bool = True) -> Verification:
    mf = path / MANIFEST_NAME
    if not mf.exists():
        return Verification("missing_files", None, "manifest.json is missing")
    raw = mf.read_bytes()
    try:
        manifest = json.loads(raw)
        files: dict = manifest.get("files") or {}
    except (ValueError, AttributeError) as e:
        return Verification("error", None, f"manifest.json is unreadable: {e}")

    # 1) signature (cheap)
    sig_p = path / SIG_NAME
    signer = manifest.get("signer")
    status, kid, msg = "unsigned", None, "module is not signed"
    if sig_p.exists():
        try:
            keys = trusted_keys(keys_dir)
        except ImportError as e:
            return Verification("error", signer, str(e))
        sig = sig_p.read_bytes()
        order = ([signer] if signer in keys else []) + [k for k in keys if k != signer]
        verified = None
        for k in order:
            try:
                keys[k].verify(sig, raw)
                verified = k
                break
            except Exception:  # noqa: BLE001 — InvalidSignature or malformed signature
                continue
        if verified:
            status, kid, msg = "valid", verified, f"signature valid (key {verified})"
        elif signer and signer not in keys:   # unknown signer: still check the files below
            status, kid, msg = "untrusted", signer, f"signed by unknown key {signer}; add its public key to keys/trusted/ to trust it"
        elif not keys:
            status, kid, msg = "untrusted", signer, "signed, but no trusted public keys are installed"
        else:
            return Verification("invalid", signer, "SIGNATURE INVALID: manifest.json was modified or the signature is corrupt")

    # 2) files
    names = sorted(files)
    missing = [n for n in names if not (path / n).is_file()]
    if missing:
        return Verification("missing_files", kid, f"missing file(s): {', '.join(missing)}")
    for n in names:
        if (path / n).stat().st_size != int(files[n].get("size", -1)):
            return Verification("invalid", kid, f"{n} has the wrong size: the module was modified or is damaged")
    if deep:
        stat_names = names + [MANIFEST_NAME] + ([SIG_NAME] if sig_p.exists() else [])
        if use_cache and _cache_matches(path, stat_names):
            msg += "; files intact (cached)"
        else:
            for n in names:
                if sha256_file(path / n) != files[n].get("sha256"):
                    return Verification("invalid", kid, f"{n} does not match its hash in the manifest: the module was modified or is damaged")
            _cache_store(path, stat_names)
            msg += "; files intact"
    return Verification(status, kid, msg)
