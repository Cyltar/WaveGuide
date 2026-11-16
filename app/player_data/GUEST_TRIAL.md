# Guest trial implementation checkpoints

## Phase 1: repository inspection

The Next.js home page calls Supabase `getUser()` and redirects unauthenticated visitors to `/login`. Email verification uses `/auth/confirm` and `verifyOtp`; login returns to `/`. The browser API client requires a bearer and calls `NEXT_PUBLIC_API_URL` directly. There is no same-origin chat proxy or checked-in backend deployment manifest. The frontend is described as hosted on Vercel; the actual backend host, its timeout and the active firewall rules cannot be established from the repository.

FastAPI `/chat` is synchronous, returns JSON, and verifies the bearer with Supabase `get_user`. Query parsing already calls Gemini. Reserve before parsing. The normal pipeline can return HTTP 200 for deterministic scope errors and Riot 429, so successful HTTP delivery cannot decide quota. Preserve the 20-game cap, same-chat Riot IDs, and current build/analysis logic. No linked account lookup for a guest. Authenticated accounts have 20 successful requests/day using the existing daily-count RPCs.

Authenticated history uses user-scoped Supabase clients, `chat_sessions.user_id`, and `chat_messages.session_id`; structured content lives in `used_context`. The backend writes the session and both messages separately. Account deletion deletes the auth user. The only SQL migration found is the game-data cache: the deployed account/chat table definitions, policies and foreign keys are not versioned in this checkout. Do not relax account-table RLS or use the service client with account-only ownership helpers. Use private guest storage and copy into the existing account tables only during an atomic claim. Verify target column types/defaults and cascades on staging before rollout.

The working tree contains pre-existing item/build code and tests, including changes to the same chat and UI files. Do not revert or include that work in guest commits. Use path-scoped commits for new files and selectively stage guest hunks in shared files. No new schema, credentials or production settings in phase 1.

## Next checkpoints

2. Private database tables, scoped RPCs, rate windows, fenced leases, transactional success/replay, cleanup, database tests.
3. Server-only cookie identity, shared chat pipeline, success classification, bounded work, preflight admission, status/history, tests. Auth always takes precedence; invalid bearer never downgrades.
4. Same-origin guest transport, initial status and restored history, request IDs, accessible signup gate, responsive tests.
5. Verified-user atomic claim, retry after verification or interruption, account-deletion compatibility.
6. Trusted ingress, environment/setup and retention instructions, Vercel Firewall guidance, full regression/build checks. Deploy/rerun migrations only with a reviewed target; no dashboard settings can be inferred from source.

## Completed checkpoints and release evidence

| Phase | Git checkpoint | Result | Migration |
|---|---|---|---|
| 1 — Inspect | eb248ab | Repository, auth, chat, ownership, deployment and compatibility audit | None |
| 2 — Database | c750511 | Private guest transcripts, windows, leases, atomic reserve/settle/replay and cleanup | 202611150001_guest_trial.sql |
| 3 — Backend | 4e3d82c | Secure cookie, authenticated proxy, account precedence, shared pipeline, error classification, bounded execution and server status/history | Uses phase 2 |
| 4 — Frontend | e5b6ee0 | Guest landing, backend allowance, retry key, fifth-response modal, disabled send and restored history | None |
| 5 — Conversion | 9b569fd | Atomic transfer after verified signup/login, retry and ownership checks, deferred email confirmation | 202611150002_guest_claim.sql |
| 6 — Deployment security / validation | Final rollout-hardening commit on codex/guest-trial | Server settings, privacy-scoped IP hashes, full prompt bounds, proxy origin checks, multi-connection and browser regression checks | Apply both earlier migrations; configure cleanup job separately |

**Implemented in code:** phases 1–6. **Manual / not deployed:** hosted schema preflight, both migrations, private runtime secrets, backend execution capacity and deadlines, Vercel WAF configuration, Supabase Cron and real staging email/auth/provider smoke checks. No production account, database, Vercel project or firewall rule was modified. The backend guest flag defaults off.

Files added: backend guest_trial.py, guest_gateway.py, guest_worker.py; two SQL migrations and database admission, concurrency and claim tests; frontend same-origin trial route, trial API client, signup modal and browser test; Python guest tests, blank environment template and these inspection/deployment notes. Files updated: shared backend app, database quota callback, Riot metadata loading, Gemini/parser bounds, home page, sidebar, chat window and frontend API client. Guest work does not require committing the pre-existing item/build changes.

Validation on the working checkout: **183 Python tests passed**. SQL admission/ownership/replay/expiry tests and claim rollback/idempotency/deletion tests passed. Native PostgreSQL with eight separate connections admitted exactly one request at a time; repeated finishes charged once and the sixth submission was blocked. Frontend lint, production build, four account unit tests, and all three browser suites passed. Verified login-first regression, guest signup with delayed verification, same-browser history restoration on login, fifth-answer visibility, and 320px layout. The real local proxy returned 200 for the same-origin no-cookie claim and 403 for a foreign origin. External Riot/Gemini, browser auth and hosted services were mocked for tests. See GUEST_DEPLOYMENT.md for setup, rollback, retention, limitations and test commands.
