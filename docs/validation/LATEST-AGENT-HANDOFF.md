# LATEST AGENT HANDOFF — LeetMath

> Machine-readable entry point for the next agent. Read this first, then the full reports in
> `docs/validation/`. Written by the Pi local-validation run of 2026-11-18.

## Current GitHub integration state (verified 2026-11-18)

| Field | Verified value |
|---|---|
| Repo | https://github.com/1998x-stack/LeetMath |
| `main` after N2.1 auth fix | `e4dc63de75ca1e846a6f70bc97fced8d66925b5d` |
| PR #6 — Pi local fixes | **MERGED** (squash into N2 feature branch) → `1d642752db60405414cab3d265375ba535083ad4` |
| PR #5 — N2 browser/CSRF/Redis | **MERGED** (squash into main) → `b7dcab7ef26c93822b59539b7fa2ead85da89c46` |
| PR #7 — CI split | **MERGED** (squash into main) → `56ad71b9c53456a2e27aae39c13ae0ddaf8d3294` |
| PR #8 — logout failure | **MERGED** (squash into main) → `e4dc63de75ca1e846a6f70bc97fced8d66925b5d` |
| Next major work | [Issue #9](https://github.com/1998x-stack/LeetMath/issues/9) — N3/P0 proof/derivation teacher manual grading workflow |
| PR #5 post-fix CI | [44236625858](https://github.com/1998x-stack/LeetMath/actions/runs/44236625858) — **3 jobs green** |
| Main N2 push CI | [44236829743](https://github.com/1998x-stack/LeetMath/actions/runs/44236829743) — **success** |
| PR #7 CI | [44236944304](https://github.com/1998x-stack/LeetMath/actions/runs/44236944304) — **4 jobs green** |
| PR #8 CI | [44237215573](https://github.com/1998x-stack/LeetMath/actions/runs/44237215573) — **4 jobs green**, Chromium **14 passed** |
| `main` push CI after #7 | [44237189022](https://github.com/1998x-stack/LeetMath/actions/runs/44237189022) — **success** |
| `main` push CI after #8 | [44237425726](https://github.com/1998x-stack/LeetMath/actions/runs/44237425726) — **in progress when this note was authored; recheck status** |

The old Pi work branch `fix/pi-local-n2-validation-20261118` at `04ab81d` and original N2 head
`08caab8` are **historical baselines, not active merge targets**. Do **not** reopen/merge
PR #5 or #6. Before making new changes, fetch `origin/main`, inspect `git status`, and
create a fresh topic branch without resetting or deleting local work.

## Latest remote CI versus earlier local acceptance

- The last Pi local run was made on the **pre-integration** feature/fix branch and showed 13 browser/auth/Redis passes,
  255 passed / 3 browser-default-skipped in each database suite, 46/46 student checks and 17/17 safety probes.
- The post-integration PR #8 **remote CI** adds one browser network-failure test, making browser/auth/Redis **14 passed**.
  All four new jobs succeed; this is not a claim that the original macOS Compose stack was revalidated at `e4dc63d`.
- The new four-job workflow separates deterministic contract/JS checks from Chromium E2E and keeps
  SQLite / PostgreSQL 16 plus Playwright screenshots/traces.
- N2 integration is complete for development/CI, **not** a production launch approval.
  Real HTTPS `Secure`/`__Host-`, proxy trust configuration, NAT-aware limiter SLO, backups/restore,
  minor-user privacy compliance, visual review and actual teacher operating procedures remain open.

## Historical local run state (Pi report, not remotely rechecked)

| Field | Value |
|---|---|
| OS / arch | macOS 27.3 / arm64, 10 vCPU, 16 GiB |
| Python | 3.12.15 in `.venv` (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`) |
| Node / Chromium | v26.13.1 / Playwright chromium 159.0.8154.6 (`python -m playwright install chromium`) |
| Stack | `docker compose -f docker-compose.yml -f /tmp/lm-compose-override.yml up -d --build` → app on **18000** (8000 is held by an unrelated local process; do not kill it), db `postgres:16` + redis `redis:7-alpine` healthy |
| Test resources | `lm-test-pg` on 15432, `lm-test-redis` on 16379 (isolated; the host 5432/6379 instances belong to the user, do not use them for tests) |
| Native path | `PATH="$PWD/.venv/bin:$PATH" PORT=18001 ./scripts/run-local.sh` (SQLite dev fallback, no Redis → process-local limiter) |
| Model note | The Pi registry has no `deepseek-flash`; nearest is `deepseek.v.4-b300/DeepSeek-V4-Flash` (vision). This run executed on `iagent/standard`; visual review of screenshots still needs a vision model or a human. |

## Historical Pi local test status (evidence in `artifacts/local-validation/2026-11-18/`)

| Check | Command | Result |
|---|---|---|
| CI parity (browser + auth + rate limit) | `LEETMATH_RUN_BROWSER_TESTS=1 LEETMATH_REQUIRE_BROWSER=1 PYTHONPATH=backend python -m pytest -q backend/tests/test_browser_e2e.py backend/tests/test_auth_security.py backend/tests/test_rate_limit.py` | **13 passed** (CI on #5: 1 failed, 12 passed) |
| Full suite SQLite | `cd backend && python -m pytest -q` | 255 passed, 3 skipped |
| Full suite PostgreSQL 16 | `cd backend && LEETMATH_TEST_DATABASE_URL=postgresql+psycopg2://leetmath:leetmath@127.0.0.1:15432/leetmath python -m pytest -q` | 255 passed, 3 skipped |
| Node CMS tests | `node --test frontend/tests/*.test.cjs` | pass 7 / fail 0 |
| Contract / generated artifacts | `cli validate fixtures/positive`, `cli ddl` vs `docs/generated/schema.postgresql.sql`, runtime OpenAPI vs `docs/generated/openapi.json` | 13/13 ok · identical · 68 paths identical |
| Migrations | `alembic upgrade head && alembic check && alembic downgrade base` (isolated SQLite + PG16 DBs) | pass, no ORM drift |
| Functional sweep (real browser) | `/tmp/lm-student-acceptance.py http://127.0.0.1:18000` | 46/46 |
| Security probes | `/tmp/lm-security-probe.py http://127.0.0.1:18000` | 17/17 |

Historical Pi note: N2 validation was green before integration. The old PR #5/#6 status described in the original Pi report is **superseded** by the current GitHub state above.

## Next actions (ordered)

1. **On the local Pi machine**: run `git fetch --all --prune`, inspect `git status` and `git branch -vv`, preserve uncommitted work and Docker volumes, and start a new branch from the latest `origin/main`. The original service on port 18000 was running **at the time of the Pi report**; its current state cannot be inferred from GitHub.
2. **N3/P0**: implement [teacher manual grading workflow #9](https://github.com/1998x-stack/LeetMath/issues/9), starting with source/schema audit and real proof/derivation teacher workflow E2E. Preserve append-only evaluation history, RBAC/IDOR, rubric totals and mathematical domain semantics.
3. **N2.1 remaining**: dependency lockfile with reproducible install; stale `#toast` text after hiding; SPA catch-all returning 200 HTML for `/openapi.json` instead of JSON 404. All changes need focused tests and separate PRs.
4. **N3/P1**: enrich structured CMS/batch edit, media upload with malware scan + signed URLs, asynchronous grading queue, then progress to grading 300+ human-labelled reference set.
5. **Before any production exposure**: test real TLS and `__Host-` cookie configuration, restricted `FORWARDED_ALLOW_IPS`, shared Redis fail-closed, NAT rate-limit calibration, load/SLO tests, legacy-session revocation during an approved rollout window, backup/restore and minors/privacy review.

## Key evidence paths (local only, gitignored — not uploaded)

```text
artifacts/local-validation/2026-11-18/pytest-browser-before-fix.txt      # red: strict mode violation
artifacts/local-validation/2026-11-18/pytest-browser-after-fix-7.txt     # green: 3 passed
artifacts/local-validation/2026-11-18/pytest-ci-quality-final.txt        # 13 passed
artifacts/local-validation/2026-11-18/cms-dom-before-fix.json            # duplicate accessible names
artifacts/local-validation/2026-11-18/student-acceptance.json            # 46/46 checks
artifacts/local-validation/2026-11-18/security-probe.json                # 17/17 checks
artifacts/e2e/*.png, artifacts/e2e/*.trace.zip                           # screenshots + Playwright traces
```

## Invariants that must not be broken (unchanged)

1. Public reads go through the single `public_revision()` gate (published + current + public + not frozen + display-allowed rights valid **now**).
2. Grading records domain constraints before SymPy simplification; equivalent-after-cancellation with a different domain → `pending_review`, never accepted and never wrong.
3. Evaluations are append-only (`previous_evaluation_id`); history keeps its original revision.
4. Import never publishes; duplicates are candidates for a human decision.
5. Reasoning self-assessment never enters `evaluations`; XP is idempotent and decoupled from grades.
6. CSRF stays mandatory for login/register and ambient cookie sessions; Redis-backed limits fail closed in production; never downgrade to process-local counting.
