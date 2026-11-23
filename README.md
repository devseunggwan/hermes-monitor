# Hermes Monitor

**Kanban worker health and provider quotas, live in the Hermes Desktop status bar.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Hermes](https://img.shields.io/badge/Hermes-%E2%89%A50.21-6f42c1.svg)](#requirements)

English | [한국어](README.ko.md)

![Hermes Monitor in the Desktop footer](docs/footer.png)

Kanban workers can stall or loop without telling you, and a quota window can run out halfway through a task. Hermes Monitor puts both signals in the footer you already look at, so you notice before it costs you a run. It makes no model calls and reads local state read-only.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Using it](#using-it)
- [How it works](#how-it-works)
- [Privacy and security](#privacy-and-security)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

## Features

- **Worker health at a glance.** A spinner and the number of running Kanban cards, coloured by the worst state: active, stalled or looping.
- **Stall and loop detection.** Stalls follow the Kanban board's own heartbeat threshold; a loop is the same tool call with the same arguments, repeated.
- **Quotas for every account you have.** Claude and Codex usage windows, DeepSeek balance, and any other provider Hermes can read usage for, across every Hermes profile.
- **Pace.** See whether you are ahead of an even burn rate, and when a window will run out at the current rate.
- **Honest figures.** Each row says whether it was read just now, held from an earlier read (`cached`) or estimated from a recorded limit; anything the monitor cannot tell reads `n/a`.
- **Read-only by design.** A quota read never refreshes or writes a credential, and no message content or tool arguments reach the UI.

## Requirements

- Hermes 0.21 or later
- Hermes Desktop

## Quick start

[**Install in Hermes**](hermes://plugin/install?repo=devseunggwan/hermes-monitor)

Or from a terminal:

```sh
hermes plugins install devseunggwan/hermes-monitor --enable
```

Then:

1. Quit Hermes Desktop completely (Command-Q) and reopen it.
2. Open **Capabilities -> Plugins -> Hermes Monitor** and switch on its Desktop half. A newly installed Desktop half starts switched off.

The two items appear on the right side of the footer.

> The `hermes-monitor` entry in the Hermes plugin catalog installs an older release (0.3.5) from the original repository. It does not include the changes listed under *Unreleased* in [CHANGELOG.md](CHANGELOG.md).

### From a local checkout

```sh
ln -s "$PWD" ~/.hermes/plugins/hermes-monitor
hermes plugins enable hermes-monitor
```

Then quit and reopen Hermes Desktop. The plugin's routes are served by the Desktop's own Hermes backend, so restarting the messaging gateway does not load them.

## Using it

| Footer item | Shows | Click to see |
|---|---|---|
| **Workers** | Spinner and count of running cards, coloured by the worst state | Each card's title, card id, assignee, runtime and last activity |
| **Quotas** | Per provider: the first usage window as a bar and percentage (or the balance), with a `×N` badge when there are several accounts | Every account's windows, reset times, pace and status |

Opening a menu requests a fresh reading. The refresh button at the top right of the Quotas menu re-reads every account at once (see [Refresh and caching](#refresh-and-caching)).

## How it works

### Worker health

Each running Kanban card is matched to its own worker session: the Kanban session whose first message names the card.

| State | Meaning |
|---|---|
| Active | Recent worker activity. A card with no heartbeat yet counts as active. |
| Stalled | The card's Kanban heartbeat is more than 120 seconds old, the board's own amber threshold. On a board without a heartbeat column: no tool call for more than five minutes. |
| Loop | The same tool with the same arguments appears at least four times in a row in the latest events. |

The footer takes the worst state across running cards: loop, then stalled, then active.

### Quotas

Providers are discovered from Hermes itself: every provider Hermes can read account usage for (Claude and Codex are built in, plus any provider that exposes a usage reader) and DeepSeek when a `DEEPSEEK_API_KEY` is found. Providers without a credential are hidden and local-only providers are skipped. A provider whose read fails stays listed with `n/a`.

- **Claude** shows its five-hour (`5h`) and weekly (`week`) windows. **Codex** shows the windows it returns (`Session`, `Weekly`). Each window has a used percentage and a reset time; reset times outside today include the date (`MM/DD HH:MM`).
- **DeepSeek** shows the remaining balance. Its key is resolved from the process environment, then the Hermes root `.env`, then the first profile `.env` (alphabetical) that contains `DEEPSEEK_API_KEY`.

#### Pace

Five-hour and weekly windows carry a pace reading. The bar in the menu marks how much of the window has elapsed, so usage to the right of the marker is ahead of an even pace. When usage at the rate so far would reach 100% before the reset, the bar turns orange (in the footer too) and the menu shows the projected run-out time. Pace is omitted in the first 5% of a window, for windows of unknown length, and for figures held from an earlier read.

#### Accounts

- Accounts are collected from every Hermes profile (the default profile and each named profile under `profiles/`) and labelled with the profile they come from.
- Pool entries signed in to the same account email are one row that says how many entries it stands for (`· 2 entries`). The provider header and the footer badge count rows.
- Each Claude row is named by the email the account is signed in with, falling back to its pool label when no email is known. Rows that would still share a name also show their pool entry id (`<label> · <id>`). Other providers show no email.

#### Account status

| Mark | Meaning |
|---|---|
| `exhausted` | Hermes benched the account on a quota limit (the bench's reset time is shown), or a window read 100% and has not reset yet. |
| `exhausted (estimated)` | Built from Hermes's bench record because no usage reading was available. |
| `cached` | The last read failed; the account's last good figures are shown, for up to six hours. |
| `n/a` | The monitor cannot tell the figure. |

An exhausted Claude or Codex account keeps its five-hour and weekly rows: the limit that was hit reads 100%, a weekly-exhausted account's five-hour row reads 0% once five hours have passed since the bench, and a row the monitor cannot tell reads `n/a`. A weekly-exhausted account shows its five-hour row only when its last reading had one, since some Claude plans have no five-hour window. Other providers show a single `limit` row.

### Refresh and caching

| What | Interval |
|---|---|
| Workers poll | every 10 seconds |
| Quotas poll and backend cache | every 60 seconds |
| Usage read per account | at most every 2 minutes |
| Backoff after a failed usage read | 5 minutes |
| Claude account email read | at most once a day (30 minutes after a failure) |
| External call timeout | 15 seconds |

The refresh button skips the two-minute interval but not the backoff after a failed read, and rests for 30 seconds after each click, because usage endpoints answer bursts with rate limits that hold for minutes.

## Privacy and security

**Workers.** The backend opens the local Kanban board and worker session databases read-only and never creates or writes a file next to them. Only activity metadata is returned: message content and tool arguments never reach the Desktop plugin, and arguments are reduced to hashes for loop detection.

**Credentials.** To aggregate quotas, the backend reads every profile's credential store (`auth.json`) one profile at a time into immutable snapshots and issues only usage requests against them. Quota reads never refresh, mutate or persist a credential, and no secret from one profile is copied into another. An expired token is skipped, not refreshed. Hermes core itself may still refresh the active profile's Anthropic token near expiry, or a Codex token after an HTTP 401, rewriting only that profile's `auth.json`. Credentials stay in the backend and are never returned to the Desktop plugin.

**Network.** The backend calls only:

- the account-usage endpoints Hermes itself uses for each listed provider, each with that account's own token;
- `GET https://api.anthropic.com/api/oauth/profile`, to read each Claude OAuth account's email;
- `GET https://api.deepseek.com/user/balance`, when a DeepSeek key is configured.

The borrowed Claude Code login's email is read locally from Claude Code's own config (`.claude.json` in `CLAUDE_CONFIG_DIR`, else the home directory), with no network call.

**Local files.** Two owner-only files under the Hermes home keep state across restarts. Backend processes on the same home share them and merge their writes under a file lock.

| File | Holds |
|---|---|
| `cache/hermes-monitor/account-emails.json` | Each Claude account's email |
| `cache/hermes-monitor/account-usage.json` | Each account's last good reading and last failed read, for the `cached` fallback and the shared backoff; entries older than six hours are dropped |

Each stored entry carries a truncated SHA-256 of the token it was read with, never the token itself. When a pool entry signs in to another account, its stored email, reading and backoff are dropped and read again. Entries removed from every pool are dropped from the email file on the next collection that reads all pools.

**What reaches the UI.** No profile names, absolute paths, tokens or other personal data are sent to the Desktop plugin, with one exception: each Claude account's sign-in email, shown in the Quotas menu only and sent nowhere else.

## Troubleshooting

**The footer items do not appear.** Check that the plugin is enabled (`hermes plugins list`) and that its Desktop half is switched on under Capabilities -> Plugins -> Hermes Monitor, then quit and reopen Hermes Desktop.

**Workers reads `n/a`.** The backend could not read the Kanban board (`kanban.db` in the Hermes home), for example because no board exists yet.

**A provider is missing from Quotas.** It has no credential in any profile, or Hermes has no usage reader for it.

**An account reads `cached`.** Its last usage read failed, often because the vendor rate-limited it. The last good figures are held for up to six hours, and the account is read again after the five-minute backoff.

## Development

Requirements: Python 3.11+ with `pytest` and `fastapi`, and Node.js for the syntax check. The tests use fixtures and make no network calls.

```sh
python3 -m pytest tests -q
node --check desktop/plugin.js
```

Run the tests from the repository root.

| Path | Role |
|---|---|
| `dashboard/plugin_api.py` | Backend routes (`/workers`, `/quotas`) and data collection |
| `dashboard/workers.py`, `dashboard/quotas.py` | Pure transformations into the payloads |
| `desktop/plugin.js` | The Desktop half: footer items and menus |

Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Related

If you mainly need provider quota tracking, see `ai-usage-tracker` in the Hermes plugin catalog. Hermes Monitor focuses on Kanban worker health and includes quotas as a secondary feature.

## License

MIT. See [LICENSE](LICENSE).
