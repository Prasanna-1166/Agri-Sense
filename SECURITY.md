# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private reporting
instead: **Security → Report a vulnerability** on this repository. Include what you found,
how to reproduce it, and the impact. You'll get a reply as soon as the maintainer can.

## Secrets and API keys

AgriSense AI never needs a secret in source code. All keys are read from environment variables
(see [`.env.example`](.env.example)):

- `.env` is git-ignored. **Only placeholders belong in `.env.example`**, which is committed.
- If a key is ever committed or pasted somewhere public, treat it as compromised: **revoke it at
  the provider and create a new one** — deleting it from a later commit does not remove it from
  Git history.
- To check a repository before pushing: `git log -p | grep -E "gsk_|sk-ant-|AIza"` should print nothing.

## What the app does to protect a public deployment

Per-IP rate limits on the chat, prediction, upload and geocoding endpoints; security headers
(`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS in
production); an 8 MB upload limit with uploads deleted right after processing; per-visitor data
isolation; no stack traces shown to users. See [`docs/deployment.md`](docs/deployment.md).
