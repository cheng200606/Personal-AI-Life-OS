# MVP Release Checklist

This checklist separates repository evidence from hosting and user research evidence. A box is complete only when an operator records the actual environment, date, version, and result.

## Repository evidence

- [x] Python lint and tests pass locally.
- [x] Web lint and production build pass locally.
- [x] Alembic schema is current and both Compose configurations parse.
- [x] Owner-scoped API tests include two users, import/export, source/account deletion, reviews, reminders, and photo paths.
- [x] Synthetic review evaluation covers 30 scenarios: conflicts, insufficient evidence, timezone boundaries, duplicates, and model failure fallback.
- [x] Support matrix, deployment guide, and backup/restore runbook are published in the repository.
- [x] [Text Alpha research protocol](research-protocol.md) and metric definitions are ready; this does not mean a study has been run.

## Required before real-data private beta

- [ ] Deploy with TLS, invitation-only registration, strong separate secrets, private PostgreSQL, private S3, and server-side encryption.
- [ ] Verify the complete API and object-store permission matrix with two real test accounts: anonymous, wrong owner, revoked, paused, deleting, and deleted access.
- [ ] Test the exact production bucket lifecycle and prove all versions and delete markers for a source are removed by the deletion endpoint.
- [ ] Run a database restore and verify tombstones replay before readiness. Test a full object-store recovery and independently preserve deletions newer than the selected snapshot.
- [ ] Measure at least 30 production-like imports of up to 5 MB and 500 text items; record P95. Measure timeline P95 on 10,000 rows in the hosted database.
- [ ] Review provider disclosure, current provider privacy/retention terms, configured input/output prices, per-call cost reserve, and external AI opt-out/fallback. Keep the provider disabled until verified.
- [ ] Check logs, metrics, CORS, security headers, backups, 5xx alerting, deletion queue/latency visibility, and incident response.
- [ ] Invite the first five users only after the previous items pass. Obtain consent, collect the same two-week workflow metrics from the development plan, and do not expand beyond ten users until reviewed.

## Current release decision

**Not ready for real personal data.** Repository-level implementation and local synthetic evidence are present. No cloud host, production bucket, domain, production restore drill, security review, or private-beta user study was available in this workspace. The operator must complete the unchecked items and record results before opening a beta.
