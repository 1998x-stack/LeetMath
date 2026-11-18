# LATEST AGENT HANDOFF — LeetMath

> Machine-readable entry point for the next agent. Read this first, then the full reports in
> `docs/validation/`. Written by the Pi local-validation run of 2026-11-18.

## Git

| Field | Value |
|---|---|
| Repo | https://github.com/1998x-stack/LeetMath |
| Acceptance baseline (N2) | `feat/n2-e2e-cookie-redis` @ `08caab892daded21139a91b05fa461460d7ff0e1` (PR #5, open) |
| `origin/main` at start | `d8b09f813b44e2620084e2cf6e246ad6ac56f19f` (PR #2 merged) |
| Work branch | `fix/pi-local-n2-validation-20261118` (pushed) |
| PR | https://github.com/1998x-stack/LeetMath/pull/6 — **stacked on #5, base = `feat/n2-e2e-cookie-redis`** (do not retarget to main while #5 is open) |
| Fix commits | `bce9ac2` test(e2e) · `27a5485` fix(cms) regions/state hooks · `0401d97` fix(auth) logout+CSRF · `e40e9c8` fix(cms) diff paths · `9031b6c` fix(ui) overflow-wrap · `8a15ffc` chore(gitignore) |
| Uncommitted | nothing (working tree clean) |

## Local run state

| Field | Value |
|---|---|
| OS / arch | macOS 27.3 / arm64, 10 vCPU, 16 GiB |
| Python | 3.12.15 in `.venv` (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`) |
| Node / Chromium | v26.13.1 / Playwright chromium 159.0.8154.6 (`python -m playwright install chromium`) |
| Stack | `docker compose -f docker-compose.yml -f /tmp/lm-compose-override.yml up -d --build` → app on **18000** (8000 is held by an unrelated local process; do not kill it), db `postgres:16` + redis `redis:7-alpine` healthy |
| Test resources | `lm-test-pg` on 15432, `lm-test-redis` on 16379 (isolated; the host 5432/6379 instances belong to the user, do not use them for tests) |
| Native path | `PATH="$PWD/.venv/bin:$PATH" PORT=18001 ./scripts/run-local.sh` (SQLite dev fallback, no Redis → process-local limiter) |
| Model note | The Pi registry has no `deepseek-flash`; nearest is `deepseek.v.4-b300/DeepSeek-V4-Flash` (vision). This run executed on `iagent/standard`; visual review of screenshots still needs a vision model or a human. |

## Test status (final tree, evidence in `artifacts/local-validation/2026-11-18/`)

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

Blockers: **none for N2 acceptance**. Remote CI for PR #6/#5 is the remaining gate.

## Next actions (ordered)

1. Watch PR #5 + #6 CI; when #5 merges, retarget/merge #6 onto `main` (or cherry-pick the 6 commits).
2. P1: split the CI quality job (contract/artifacts/JS vs Chromium E2E) so failures are attributable; keep uploading `artifacts/e2e/`.
3. P1: calibrate the rate-limit thresholds against real school NAT/proxy traffic and run an SLO test.
4. P1: structured CMS editor depth (batch edit, richer diff), media upload + malware scan + signed URLs, async grading queue — see `docs/13 §6`.
5. P2 (found this run): `GET /openapi.json` is swallowed by the SPA catch-all (returns 200 HTML); serve a JSON 404 for unknown API paths.
6. P2 (found this run): `#toast` hides with `opacity: 0` but keeps its text — stale messages can satisfy later assertions or be re-announced by screen readers.
7. P2: add a dependency lockfile; decide whether to gate the full ruff rule set.
8. Before any production exposure: `LEETMATH_ENV=production` + `LEETMATH_COOKIE_SECURE=1` + unique `LEETMATH_CSRF_SECRET` + shared `LEETMATH_REDIS_URL` + `FORWARDED_ALLOW_IPS` restricted; revoke legacy sessions once (`UPDATE auth_sessions SET revoked = TRUE WHERE revoked = FALSE;`).

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
