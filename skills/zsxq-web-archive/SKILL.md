---
name: zsxq-web-archive
description: Scan current Knowledge Planet memberships and archive authorized web topics and attachments through deterministic, resumable jobs when the normal ZSXQ Skill API is unavailable. Use for bounded historical ZSXQ web backfills; do not use to bypass expired memberships or group download restrictions.
---

# ZSXQ web archive

Use `scripts/zsxq_web.py`; it delegates to the portable IR System CLI. Do not inspect pages, copy cookies, invent selectors, or choose a route yourself. The CLI owns membership checks, Skill probing, permissions, browser state, retries, manifests, and checkpoints.

Read [cli-contract.md](references/cli-contract.md) before the first execution in an environment.

1. Run `python3 scripts/zsxq_web.py doctor`. If Chrome or `zsxq-cli` authentication is unavailable, stop and report the JSON error.
2. Prefer one `backfill` command with an inclusive `--start`, `--end`, archive root, and exactly one explicitly requested `--group-id`. It always re-scans every joined star, creates a fresh bounded plan, and resumes the selected archive checkpoint. Never infer or substitute a group ID.
3. If the dedicated browser profile has not been logged in, run `login` once and ask the operator to scan the displayed QR code. Never read, print, export, or transmit cookies or tokens.
4. For first-time diagnosis, run `probe --group-id ...`. For routine work, use `backfill`; only use the lower-level `prepare` then `run --plan ...` sequence for debugging. `run` refuses stale or incomplete all-group scans.
5. Report the manifest paths, records added, attachment successes/failures, and explicit coverage note. Web infinite scrolling never proves complete source coverage.

On an execution error, report the returned `error.details` (including diagnostic, stage, manifest and checkpoint paths). Exit 1 is a maintenance fault: stop after the first occurrence. Do not repeat `backfill` or run additional diagnostic commands automatically. These operator rules apply to download workers; a maintainer explicitly asked to repair the adapter may inspect and modify its implementation.

Treat these results as terminal until the operator changes external state: `membership_expired`, `download_disabled_by_group`, `route_changed`, and `human_login_required`. Do not work around them. Do not repeatedly retry `rate_limited`, authentication, CAPTCHA, or browser-policy failures; stop for operator action.

Use the CLI's default browser mode. On macOS it opens a normal dedicated browser window because Chrome 153's headless mode crashed in live testing. Keep that window open while the command runs. Other platforms default to headless. Run one archive process at a time; the CLI lock prevents concurrent writers.
