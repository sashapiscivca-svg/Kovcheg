# Module integrity and signatures

[Українська](../uk/integrity.md) · [Docs index](README.md)

A knowledge module that someone has changed, deliberately or by disk corruption, can give wrong instructions in a crisis. Kovcheg makes such changes visible.

## How it works

- After every build, `manifest.json` records the SHA-256 hash and size of every file of the module (`kovcheg.db`, `dense.f16.npy`, `sparse.npz`).
- If `keys/private_key.pem` exists, the builder signs the exact bytes of `manifest.json` with Ed25519 and writes `manifest.sig`. The manifest also records the signer's key id (the first 16 hex characters of the SHA-256 of the public key).
- The application opens modules strictly read-only, so normal use never changes a file.
- Verification checks the signature, then the file sizes, then (deep mode) the SHA-256 of every file. A successful deep check is cached in `<module>/.verified.json`, keyed by each file's size and modification time, so it is not repeated on every start. On read-only media the cache is skipped and the check runs again.

## Statuses

| Status | Meaning | What the UI does |
|---|---|---|
| **valid** | signature by a trusted key, files intact | green badge |
| **unsigned** | no signature, files match the manifest | neutral badge; fine for modules you built yourself |
| **untrusted** | valid signature by a key that is not in your trust store | amber badge; check who made the module |
| **INVALID** | a file was modified, is missing, or the signature does not match | red warning; the module is unchecked by default |

## Keys and trust

```bash
kovcheg keygen                 # keys/private_key.pem (mode 0600) and keys/public_key.pem
kovcheg sign first-aid         # sign an existing module
kovcheg verify                 # deep check of all modules; exit code 1 if any is INVALID
kovcheg verify first-aid --quick
```

Trusted public keys are your own (`keys/public_key.pem`, or derived from the private key) and every `keys/trusted/*.pem`. To distribute modules, publish your `public_key.pem` through a channel your users already trust, for example printed on paper or in person, and ask them to place it in `keys/trusted/`.

## What a signature does not do

- It does not prove that the content is correct, current or safe. It proves only who built the module and that it has not changed since.
- The verification cache can be fooled by an attacker who edits a file while keeping its size and restoring its exact modification time. `kovcheg verify` always performs a full re-hash and is not affected.
- Anyone with your private key can sign in your name. Keep it offline and backed up, and never ship it inside a kit.
