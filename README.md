# CIPHER — Behavioral Risk-Scoring Analytics Engine

A PostgreSQL-based system that scores authentication events for risk by comparing
each login against that specific user's own history, then outputs one ranked
priority queue of the riskiest logins with explainable reasons.

---

## Problem Statement

Most login-monitoring systems rely on static, one-size-fits-all rules: flag every
failed login, flag every new device, flag every login outside business hours.
These rules generate a flood of noise because they ignore the fact that "normal"
looks different for every user — a salesperson who travels weekly and an
accountant who never leaves their desk have very different baselines.

CIPHER takes a behavioral approach instead. Every login event is scored against
that specific user's own history: has this device been seen before, has this
location been seen before, how long has it been since their last login, and
does this login fit a physically plausible travel pattern compared to their
last one. Those behavioral signals are combined with a smaller set of static
rules into one composite risk score, producing a ranked, explainable priority
queue analysts can act on — the same layered-scoring approach used in
production fraud and credit-risk systems.

---

## Architecture

```
CSV Generation (Python) → PostgreSQL Warehouse → Scoring View → Priority Queue View
     generate_data.py         5 tables            risk_scores      (top 20, ranked)
     load_data.py            (star schema)      (3-layer scoring)
```

**Stack:** PostgreSQL 17, Python (pandas, SQLAlchemy, psycopg2), pgAdmin4, VS Code

**Files:**
```
cipher/
├── sql/
│   ├── 01_create_warehouse.sql   -- schema + indexes
│   ├── 02_scoring_engine.sql     -- the composite risk-scoring view
│   └── 03_priority_queue.sql     -- top-20 ranked output with reasons
├── scripts/
│   ├── generate_data.py          -- synthetic data + 3 planted incidents
│   └── load_data.py              -- loads CSVs into Postgres
├── data/                         -- generated CSVs
└── README.md
```

---

## ER Diagram

```
dim_user ───┐
dim_device ─┤
dim_location┼──► fact_login_events ──► risk_scores (view) ──► priority queue (view)
dim_application┘
```

`fact_login_events` is the central fact table (7,140 rows: 40 users, 4 months of
activity). Each row references a user, device, location, and application, with
a timestamp and success/failure status. All four dimension tables are small,
static lookup tables.

---

## The Three Planted Incidents

To validate the scoring engine, three realistic incident patterns were planted
into ~4 months of otherwise normal synthetic login activity.

**1. Credential compromise (`sarah6`)**
A slow brute-force attack — 6–10 failed login attempts per day over 3 days —
followed by a successful breach at 3 AM from a device and location this user
had never used before, immediately followed by a pivot into `Finance_Ledger`,
a high-sensitivity application.

**2. Impossible travel (`william16`)**
Two successful logins, 15 minutes apart, from London and Singapore — a
physically impossible distance to cover in that time window.

**3. Dormant account reactivation (`linda26`)**
An account that had been completely inactive for over 60 days suddenly logged
in and accessed `Admin_Console`, a high-sensitivity application — on the same
device and location the user had always used, meaning the anomaly is purely
about *timing*, not device or location.

---

## Composite Risk-Scoring Engine

Three layers combine into one score:

```
Static Rule Score + Behavioral Score + Impossible-Travel Score = Composite Risk Score
```

**Layer 1 — Static rules**

| Rule | Points |
|---|---|
| Failed login | +10 |
| New device (never used by this user before) | +20 |
| Unusual location (never used by this user before) | +25 |
| After-hours login | +10 |
| 5+ failures same day | +30 |
| Sensitive app accessed in a risky context* | +15 |
| Dormant account reactivation (60+ days silent) | +35 |
| Impossible travel (implausible speed between consecutive logins) | +40 |

\* "Risky context" = new device, new location, **or** 60+ days dormant — see
tuning note below.

**Layer 2 — Behavioral scoring**
Every login is compared against that user's own history using window
functions: `MIN(event_timestamp) OVER (PARTITION BY user_id, device_id)` and
the location equivalent determine whether this is the first time this user has
used this device/location. `LAG(event_timestamp) OVER (PARTITION BY user_id
ORDER BY event_timestamp)` measures days since the user's last login, catching
dormant-account reactivation.

**Layer 3 — Impossible travel**
`LAG()` over each user's successful logins (ordered by time) retrieves the
previous login's coordinates and timestamp. A Haversine formula computes the
distance between the two points; dividing by elapsed time gives implied
travel speed. Anything faster than ~900 km/h (commercial jet speed) over a
real distance (>300 km, to filter out noise) is flagged.

**Output:** one `risk_scores` view with a `composite_score` and a `risk_tier`
(LOW / MEDIUM / HIGH / CRITICAL), and one `priority_queue` view ranking the
top 20 events with a plain-English `reasons` column.

---

## Before / After: Raw Event → Scored, Explained Output

**Raw event (from `fact_login_events`):**

| event_id | user_id | device_id | location_id | application_id | event_timestamp | login_status |
|---|---|---|---|---|---|---|
| 1027 | 6 | 53 | 9 | 1 | 2026-04-30 07:17:00 | failure |

**Scored output (from `priority_queue`):**

| rank | username | location | app | composite_score | risk_tier | reasons |
|---|---|---|---|---|---|---|
| 1 | sarah6 | Dubai, UAE | EmailSuite | 85 | CRITICAL | Failed login attempt, new device never used by this user, location never used by this user, after-hours login, five or more failures same day |

The raw row alone tells an analyst almost nothing. The scored output tells them
immediately: this is a known-bad pattern, on a device/location this user has
never touched, escalating over multiple failures — worth investigating first.

---

## Why Behavioral Scoring Beats Static Thresholds

A static system might flag every failed login or every new device equally,
for every user, all the time — creating constant noise for users who travel
often or occasionally mistype a password. CIPHER instead asks "has *this*
user ever done this before?" for every event. A new device is only meaningful
in the context of that user never having used one before; a login at 3 AM is
only meaningful layered against a genuine brute-force pattern and a completely
unfamiliar device and location. This is what let the system correctly separate
three very different incidents — a slow-building attack, a physically
impossible jump, and a silent-then-sudden reactivation — using the same eight
rules, without hand-tuning a separate rule for each incident type.

---

## Rule Tuning & False-Positive Notes

Two real issues were found and addressed during validation — worth documenting
honestly rather than hiding:

**1. First-login cold start (fixed).**
A user's very first-ever recorded event has no prior history to compare
against, so the "new device" and "new location" rules fired on every user's
first login in the dataset, even though it's completely normal — this is a
known real-world problem in behavioral/UEBA systems. Fixed by suppressing
both rules whenever `days_since_last_login IS NULL` (which only occurs on a
user's first-ever recorded event).

**2. Dual-home-location impossible travel (documented, not fixed).**
Several synthetic users were assigned two legitimate "home" locations (e.g. a
remote worker with two offices). Because the data generator picks between a
user's home locations at random with no enforced travel-time realism, a user
can occasionally "teleport" between their own two legitimate cities within an
implausible window, triggering a false-positive impossible-travel flag. This
is a genuine limitation, not a bug in the scoring logic: a production system
would need per-user location whitelisting, VPN-awareness, or a minimum-time
constraint between a user's own known locations before this rule would be
production-ready. Documented here as a known limitation, deliberately left as
future work rather than over-fit to this synthetic dataset.

---

## Performance: `EXPLAIN ANALYZE` Before & After

The first implementation of the behavioral layer used correlated subqueries
(`EXISTS`, `MAX`, `COUNT` with a correlated `WHERE` clause) to check each
event against a user's history. `EXPLAIN ANALYZE` revealed this was O(n²):
each of 7,140 rows triggered a fresh scan of the other rows, roughly 51
million row comparisons.

| | Before (correlated subqueries) | After (window functions) |
|---|---|---|
| Execution Time | 65,449.934 ms (~65.4 sec) | 491.519 ms (~0.49 sec) |
| Speedup | — | **~133×** |
| Method | `EXISTS`/`MAX`/`COUNT` subqueries, `loops=7140` each | `MIN() OVER`, `LAG() OVER`, `COUNT() FILTER OVER` — single sort-and-partition pass per window |

Rewriting `history_check` to use window functions instead of correlated
subqueries — the technique the design called for from the start — reduced
execution time by roughly 133x, with byte-for-byte identical output (verified
against all three planted incidents before and after the change).

---

## What I'd Add With More Time

*(Explicitly scoped as future work — not implied to be done.)*

- A materialized view (`mv_daily_user_behavior`) precomputing each user's
  daily baseline (typical devices, locations, login hours), refreshed on a
  schedule, so the scoring view doesn't recompute behavioral aggregates on
  every query — useful at much larger scale than this dataset.
- Per-user location whitelisting to resolve the dual-home-location false
  positive noted above.
- A feedback loop where an analyst's true-positive/false-positive
  determination on a flagged event adjusts future point weights for that
  rule — moving from static point values toward a lightly adaptive system.
- Extending the impossible-travel check to account for known VPN exit nodes,
  which legitimately produce large apparent location jumps with no travel
  time at all.

---

## Resume Summary

> **CIPHER — Behavioral Risk-Scoring Engine**
> Designed a PostgreSQL-based composite risk-scoring system that converts
> authentication events into ranked, explainable risk assessments — combining
> static rule-based scoring with behavioral SQL window-function analysis
> (comparing each event against a user's own history) to detect credential
> compromise, impossible-travel, and dormant-account-reactivation patterns.
> Diagnosed and resolved an O(n²) performance bottleneck via `EXPLAIN ANALYZE`,
> rewriting correlated subqueries as window functions for a ~133x speedup.#   C i p h e r  
 