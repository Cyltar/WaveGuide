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
