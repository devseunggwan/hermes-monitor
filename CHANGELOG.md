# Changelog

## Unreleased

- A worker reads as stalled when its Kanban heartbeat is more than 120 s old, the threshold the Kanban board uses for its amber mark, instead of after five minutes without a tool call. A long tool run or generation keeps the heartbeat fresh, so it no longer reads as stalled; a board without a heartbeat column keeps the five-minute tool-call rule.
- Worker activity is read from the card's own session (the Kanban session that opens with its card id), not the session started closest to the run. Cards started together on one profile no longer read each other's tool calls.
- Fixed the Worker item failing intermittently: when no process had the Kanban board open, SQLite had removed its `-wal`/`-shm` files and the read-only connection could not open the board. It now reads the file as it is when no `-wal` exists, still without creating or writing any file.
- Each Claude account row shows the email it is signed in with, so pool labels that hide the same login (or one label shared by two logins) can be told apart. OAuth accounts read it from Anthropic's OAuth profile endpoint once a day per account; the borrowed Claude Code login reads it from Claude Code's own config, with no network call.
- Accounts that share a label in one provider show their pool entry id (`<label> · <id>`), so the rows can be told apart.
- An account whose reading shows a window at 100% (not yet reset) shows `exhausted` instead of `ok`, even before Hermes benches it.
- A refresh button at the top right of the Quotas menu re-reads every account now, skipping the two-minute refetch interval but not the backoff after a failed read; it rests for 30 seconds after each click.
- Exhausted Claude and Codex accounts keep their five-hour and weekly rows instead of collapsing into one `limit` row: the limit that was hit reads 100%, a weekly-exhausted account's five-hour row reads 0% once five hours have passed since the bench, and a row that cannot be told reads `n/a`.
- Quota windows show pace: an elapsed-time marker on each bar, an orange bar when usage at the current rate runs out before the reset, and the projected run-out time in the menu.
- Fixed borrowed credentials (`claude_code`, `env:*`) always showing `n/a`: their secret is resolved read-only inside the profile scope; an expired Claude Code token is skipped, never refreshed.
- Providers Hermes cannot read usage for (no fetcher, or DeepSeek without a key) are no longer listed as permanent `n/a` rows.
- Accounts benched for quota exhaustion show `exhausted` with the bench's reset time instead of `n/a`, and the active marker follows the first account that is not benched.
- A failed usage read (e.g. the endpoint's 429) falls back to the account's last good figures, marked `cached`, for up to six hours.
- Reset times outside today include the date (`MM/DD HH:MM`).
- Quotas refresh every 60 seconds (backend cache and footer poll were 5 minutes).

## 0.3.5

- Security: quota reads now resolve the active Hermes profile as their own home and use immutable credential snapshots for every profile, including the active profile. The root home is still included as a read-only sibling when a named profile is active, preventing expired root credentials from being refreshed or copied into the active profile's `auth.json`.

## 0.3.3

- Security: quota aggregation is now strictly read-only for non-active profiles. The old loader installed a sibling profile's home and secret scope only while loading its credential pool, then handed back the live pool and called `peek()`/`select()` on it after the scope was reset — which could prune aged-out DEAD entries, refresh an expired Anthropic OAuth token, and persist the result into the wrong profile's `auth.json`. Sibling profiles are now read into an immutable snapshot inside their own scope and only usage requests are issued against it; an expired sibling token reports `n/a` instead of being refreshed. Only the backend's own profile refreshes its own token. The process-global `HERMES_HOME` env-swap fallback was removed in favour of the context-local home override.

## 0.3.2

- Fixed Claude quotas still showing `n/a` on the Desktop backend: the multiplexed serve fails closed on unscoped credential reads, so the pool loader now runs inside each profile's secret scope and can resolve the OAuth/Keychain token.
- Quotas now show only providers with a real credential (OAuth token, API key, or a resolved DeepSeek key). Unconfigured providers are hidden; a provider that has credentials but is momentarily in error stays visible with its status.

## 0.3.1

- Fixed Claude quotas stuck at `n/a` on the Desktop backend: a credential store shared by several profiles was queried once per profile, so the same accounts were fetched 8 times per refresh. Anthropic's usage endpoint answers those bursts with `429` (about three minutes of `Retry-After`) and every window fell back to `n/a`. Each credential is now fetched once per collection and the result is reused across profiles.

## 0.2.2

- Packaging/compliance for Hermes plugin publication: completed plugin.yaml metadata (author, license, repository, permissions), manifest schema, LICENSE file, install docs.

## 0.2.1

- Fixed Claude quotas showing `n/a` for the active credential-pool account (OAuth token handling).
- Quotas now dynamically enumerate every active Hermes provider instead of a hardcoded set (local-only providers are excluded).

## 0.2.0

- Quotas now reflect each provider's active credential-pool account.
- The footer identifies the active account, while the menu lists every pool account with its plan, usage percentages, and an active marker.
- DeepSeek quota details now report the non-secret credential `key_source`.