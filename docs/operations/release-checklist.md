# MVP Release Checklist

This checklist gates exposing the instance to other people. A solo local instance does not need TLS, invitation codes, a hosted database, or a private bucket; keep a consistent copy of `data/` instead. See [Solo local use](deployment.md#solo-local-use).

This checklist separates repository evidence from hosting and user research evidence. A box is complete only when an operator records the actual environment, date, version, and result.

## Scope

- **Solo local candidate (current):** the Windows desktop D0–D5 build passed local acceptance on 2026-11-27 using synthetic data. It runs on one local Windows account, needs no hosted infrastructure, and is neither signed nor distributed to other people. See [desktop acceptance](desktop-acceptance.md).
- **Public distribution:** requires code signing, SmartScreen reputation, and update hosting before any installer is shared outside this machine. In-repo signing/updater build support is ready; see the [public distribution runbook](public-distribution.md).
- **Hosted or other-people beta:** every unchecked item below still applies. Real personal data is not approved yet.

## Repository evidence

- [x] Python lint and tests pass locally.
- [x] Web lint and production build pass locally.
- [x] Alembic schema is current and both Compose configurations parse.
- [x] [GitHub Actions Linux matrix and Docker Compose smoke](https://github.com/cheng200606/Personal-AI-Life-OS/actions/runs/45466928521) pass for the audited baseline `55831c2`. The smoke checks startup and readiness.
- [x] Owner-scoped API tests include two users, import/export, source/account deletion, reviews, reminders, and photo paths.
- [x] Synthetic review evaluation covers 30 scenarios: conflicts, insufficient evidence, timezone boundaries, duplicates, and model failure fallback.
- [x] Support matrix, deployment guide, and backup/restore runbook are published in the repository.
- [x] [Text Alpha research protocol](research-protocol.md) and metric definitions are ready; this does not mean a study has been run.

## Required before real-data private beta

- [ ] Deploy with TLS, invitation-only registration, strong separate secrets, private PostgreSQL, private S3, and server-side encryption.
- [ ] Run browser and Obsidian acceptance on the release candidate. Verify photo-folder import and real OCR in the target image, and confirm PostgreSQL worker recovery through a restart.
- [ ] Verify the complete API and object-store permission matrix with two real test accounts: anonymous, wrong owner, revoked, paused, deleting, and deleted access.
- [ ] Test the exact production bucket lifecycle and prove all versions and delete markers for a source are removed by the deletion endpoint.
- [ ] Run a database restore and verify tombstones replay before readiness. Test a full object-store recovery and independently preserve deletions newer than the selected snapshot.
- [ ] Measure at least 30 production-like imports of up to 5 MB and 500 text items; record P95. Measure timeline P95 on 10,000 rows in the hosted database.
- [ ] Review provider disclosure, current provider privacy/retention terms, configured input/output prices, per-call cost reserve, and external AI opt-out/fallback. Keep the provider disabled until verified.
- [ ] Check logs, metrics, CORS, security headers, backups, 5xx alerting, deletion queue/latency visibility, and incident response.
- [ ] Invite the first five users only after the previous items pass. Obtain consent, collect the same two-week workflow metrics from the development plan, and do not expand beyond ten users until reviewed.

## Current release decision

**Hosted or other-people release: not ready for real personal data.** The solo local Windows desktop candidate passed D0–D5 acceptance on 2026-11-27 with synthetic data only. Repository-level implementation, local synthetic evidence, and a version-aligned 0.1.1 release candidate are present, but no cloud host, production bucket, domain, production restore drill, security review, signed installer, or private-beta user study was available in this workspace. Real personal data remains unapproved; the operator must complete the unchecked items and record results before opening a beta to other people.
