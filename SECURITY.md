# Security Policy

QuantScript is a **local-first, offline-by-default** desktop/browser app. All inference and storage happen on your own machine; the only outbound traffic is the one-time model download from Hugging Face and the web-search/deep-research features you explicitly enable. Because of this model, the most security- sensitive areas are: the local HTTP API (sidecar), file/attachment handling, and the outbound fetches performed during web search (SSRF surface).

## Security model & trust boundaries

QuantScript assumes a **single trusted user on a trusted machine**. The backend binds to loopback (`127.0.0.1`) only and is never meant to be exposed to a network. Within that model, two deployment modes have **different authentication postures**:

- **Desktop app.** The Tauri shell starts the backend on a **random loopback port** and generates a fresh **32-byte sidecar token** on every launch. Every request must carry that token (`X-Sidecar-Token`, constant-time compared), so other local processes cannot call the API without it.
- **Browser mode.** When you run the backend yourself and open the web UI, there is **no sidecar token: the local API is unauthenticated.** Requests from *web pages* are still defended in depth (loopback-only binding, a Host-header check against DNS rebinding, a locked-down CORS policy, and a cross-origin guard that blocks forged cross-site writes). However, because the guard intentionally allows requests that carry **no `Origin` header**, **any other process running under your user account on the same machine can read, create, or delete your conversations and send inference requests.**

What this means in practice:

The tool is intended for a single-user laptop.

### Desktop file-read bridge

The desktop app reads user-selected files (e.g. attachments) through two Rust commands, `authorize_file_path` and `read_binary_file`. A path must first be authorized, and reads are constrained by a substring denylist and a file-size cap. Because these commands are reachable from webview JavaScript, a compromised renderer could in principle request reads of other authorized paths. We accept this as a desktop trust-boundary trade-off: it is mitigated by the restrictive CSP (no remote script, no inline script), the loopback-only backend, and the single-trusted-user model above. Reducing the bridge to dialog-bound selections is tracked as a possible future hardening step.

Accordingly, attacks that require an attacker to already have local code execution (or another local account) on the machine are **out of scope** (see [Scope](#scope)).

## Code signing & distribution

Code signing is **per-platform** and independent of QuantScript's runtime security model (loopback-only API, sidecar token, CSP). It governs how the OS treats the installer on first launch, not how the app behaves once running.


| Platform    | Current posture                                                              | What the user sees                                                                                               |
| ----------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **macOS**   | **Signed with a Developer ID certificate and notarized** by Apple (stapled). | No Gatekeeper warning; opens normally, even offline.                                                             |

Until signing certificates are in place, **every desktop installer ships with a matching `.sha256`** so downloaders can verify integrity:

```bash
# macOS
shasum -a 256 -c QuantScript_<version>_<arch>.dmg.sha256
```

## Supported versions

Only the latest released version receives security fixes. Please make sure you're on the newest release before reporting.


| Version | Supported |
| ------- | --------- |
| latest  | yes       |
| older   | no        |


## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Instead, report privately via one of:

- GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) ("Report a vulnerability" under the repository's **Security** tab), or
- Email **[info@quantscript.io](mailto:info@quantscript.io)** with the subject line `SECURITY:`

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a proof of concept is ideal).
- Affected version / commit and your OS.

### What to expect

- **Acknowledgement** within 5 business days.
- A triage assessment and, where applicable, a remediation timeline.
- Credit in the release notes if you'd like it (let us know).

## Scope

In scope:

- The local backend API (`backend/app/`), especially auth, sanitization, attachment handling, and conversation storage.
- The SSRF protections around web search / article fetching (`backend/app/engine/llm/web_search.py`).
- The Tauri desktop shell (`frontend/src-tauri/`), including the sidecar token handshake and the file-read commands.

Out of scope:

- Vulnerabilities that require an attacker to already have local code execution or physical access to the machine.
- Issues in third-party model weights or in upstream dependencies (please report those to the respective projects; we will update once a fix is available).
- Denial of service from intentionally pathological local input.

## Known accepted advisories

Some advisories are knowingly accepted (and suppressed in CI) because no fixed upstream path is available and they are not reachable in our threat model:


| Advisory       | Component                                              | Why accepted                                                                                                                                                                                                 |
| -------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CVE-2025-69872 | `diskcache==5.6.3` (transitive via `llama-cpp-python`) | No fixed release available upstream. `diskcache` is used only for local, single-user, on-disk caching on loopback; it is not exposed to the network. Tracked for removal once a fixed dependency path ships. |


The dependency audit in CI (`.github/workflows/security-checks.yml`) explicitly
documents and ignores this advisory; new advisories are not suppressed by
default.

Thank you for helping keep QuantScript users safe.