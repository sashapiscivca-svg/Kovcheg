# Security

[Українська](docs/uk/SECURITY.md)

## Threat model in brief

Kovcheg runs offline on a single machine. The assets worth protecting are the **integrity of the knowledge modules** (a tampered first-aid module can kill), the **privacy of the questions** people ask, and the **availability** of the system in a crisis.

| Risk | What Kovcheg does | What you should do |
|---|---|---|
| A module is modified, corrupted or replaced | `manifest.json` lists SHA-256 hashes of every module file; `kovcheg verify` and the interface re-check them; an Ed25519 signature binds the manifest to a key | Sign modules you distribute; accept modules only from people whose public key you have in `keys/trusted/` |
| Malicious document content (HTML/script in documents) | All document text is escaped before display; nothing from a document is executed | — |
| Malicious model files | Kovcheg loads models only from local paths you configure; it never downloads | Download models only from the official repositories listed in [docs/en/models.md](docs/en/models.md); prefer `.safetensors` and GGUF files |
| Questions leaking | No network calls, no telemetry; the web interface listens on 127.0.0.1 by default | Set `host = "0.0.0.0"` only on a network you trust; there is no authentication |
| Private signing key theft | Key file is created with mode 0600 | Keep `keys/private_key.pem` off machines you distribute; back it up offline |

The signature proves who built a module and that it has not changed since. It does **not** prove that the content is correct.

## Reporting a vulnerability or a dangerous answer

Use **GitHub private vulnerability reporting** on this repository ("Security" tab → "Report a vulnerability"). Do not open public issues for vulnerabilities. Dangerous or misleading answers that do not reveal anything sensitive can be reported as normal issues with the label `safety`.

Include the Kovcheg version (`kovcheg --version`), your operating system, the steps to reproduce, and what you expected. We aim to acknowledge reports within 7 days.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | yes |
| prototype (pre-1.0, `ark-system`) | no — migrate modules with `kovcheg migrate` |
