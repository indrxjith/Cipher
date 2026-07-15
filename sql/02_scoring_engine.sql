-- 02_scoring_engine.sql
-- CIPHER: Composite Risk-Scoring Engine
-- Layer 1: Static rules | Layer 2: Behavioral (own-history) | Layer 3: Impossible travel

DROP VIEW IF EXISTS risk_scores;

CREATE VIEW risk_scores AS

WITH

-- ============================================================
-- BASE: enrich every event with user/device/location/app context
-- ============================================================
base AS (
    SELECT
        f.event_id,
        f.user_id,
        u.username,
        f.device_id,
        d.device_fingerprint,
        f.location_id,
        l.city,
        l.country,
        l.latitude,
        l.longitude,
        f.application_id,
        a.app_name,
        a.sensitivity_level,
        f.event_timestamp,
        f.login_status,
        EXTRACT(HOUR FROM f.event_timestamp) AS login_hour,
        EXTRACT(DOW FROM f.event_timestamp) AS day_of_week
    FROM fact_login_events f
    JOIN dim_user u ON f.user_id = u.user_id
    JOIN dim_device d ON f.device_id = d.device_id
    JOIN dim_location l ON f.location_id = l.location_id
    JOIN dim_application a ON f.application_id = a.application_id
),

-- ============================================================
-- LAYER 2 INPUTS: has this user ever used this device/location BEFORE this event?
-- Rewritten to use window functions instead of correlated subqueries —
-- the original correlated-subquery version re-scanned the base data once
-- per row (O(n^2), ~65s on 7,140 rows). Window functions compute each
-- partition in a single sort-and-scan pass (O(n log n)).
-- ============================================================
history_check AS (
    SELECT
        b.*,
        -- Device is "new" exactly when this event IS the earliest recorded
        -- use of this device by this user.
        (MIN(b.event_timestamp) OVER (PARTITION BY b.user_id, b.device_id) < b.event_timestamp)
            AS device_seen_before,

        (MIN(b.event_timestamp) OVER (PARTITION BY b.user_id, b.location_id) < b.event_timestamp)
            AS location_seen_before,

        -- Days since this user's previous login (any device/location).
        -- NULL means this is the user's first-ever recorded event (no baseline yet).
        EXTRACT(EPOCH FROM (
            b.event_timestamp - LAG(b.event_timestamp) OVER (PARTITION BY b.user_id ORDER BY b.event_timestamp)
        )) / 86400.0 AS days_since_last_login,

        -- Failures by this user on the same calendar day
        COUNT(*) FILTER (WHERE b.login_status = 'failure')
            OVER (PARTITION BY b.user_id, DATE(b.event_timestamp)) AS failures_same_day

    FROM base b
),

-- ============================================================
-- LAYER 3: IMPOSSIBLE TRAVEL — compare each login to the PRIOR login (success only)
-- using LAG() over each user's successful logins ordered by time
-- ============================================================
travel_check AS (
    SELECT
        h.*,
        LAG(h.latitude) OVER (PARTITION BY h.user_id ORDER BY h.event_timestamp) AS prev_lat,
        LAG(h.longitude) OVER (PARTITION BY h.user_id ORDER BY h.event_timestamp) AS prev_lon,
        LAG(h.event_timestamp) OVER (PARTITION BY h.user_id ORDER BY h.event_timestamp) AS prev_ts,
        LAG(h.city) OVER (PARTITION BY h.user_id ORDER BY h.event_timestamp) AS prev_city
    FROM history_check h
    WHERE h.login_status = 'success'
),

travel_speed AS (
    SELECT
        t.*,
        -- Haversine distance in km between prev location and this one
        CASE
            WHEN t.prev_lat IS NULL THEN NULL
            ELSE (
                2 * 6371 * ASIN(
                    SQRT(
                        POWER(SIN(RADIANS(t.latitude - t.prev_lat) / 2), 2) +
                        COS(RADIANS(t.prev_lat)) * COS(RADIANS(t.latitude)) *
                        POWER(SIN(RADIANS(t.longitude - t.prev_lon) / 2), 2)
                    )
                )
            )
        END AS distance_km,
        CASE
            WHEN t.prev_ts IS NULL THEN NULL
            ELSE EXTRACT(EPOCH FROM (t.event_timestamp - t.prev_ts)) / 3600.0
        END AS hours_since_prev
    FROM travel_check t
),

travel_flagged AS (
    SELECT
        ts.event_id,
        CASE
            WHEN ts.distance_km IS NOT NULL
             AND ts.hours_since_prev IS NOT NULL
             AND ts.hours_since_prev > 0
             AND (ts.distance_km / ts.hours_since_prev) > 900   -- faster than a commercial jet
             AND ts.distance_km > 300                            -- ignore short hops / noise
            THEN TRUE ELSE FALSE
        END AS impossible_travel_flag,
        ts.distance_km,
        ts.hours_since_prev,
        ts.prev_city
    FROM travel_speed ts
),

-- ============================================================
-- SCORING: combine all rules into a composite score with reasons
-- ============================================================
scored AS (
    SELECT
        h.event_id,
        h.username,
        h.device_fingerprint,
        h.city,
        h.country,
        h.app_name,
        h.sensitivity_level,
        h.event_timestamp,
        h.login_status,

        -- Layer 1: Static rules

        (CASE WHEN h.login_status = 'failure' THEN 10 ELSE 0 END) AS pts_failed_login,

        -- Tuning note: a user's very first-ever recorded event has no prior
        -- history to compare against, so "new device"/"new location" would
        -- always fire on it even though it's normal. Suppress both rules when
        -- days_since_last_login IS NULL (only true on that user's first-ever event).
        (CASE WHEN NOT h.device_seen_before AND h.days_since_last_login IS NOT NULL
              THEN 20 ELSE 0 END) AS pts_new_device,

        (CASE WHEN NOT h.location_seen_before AND h.days_since_last_login IS NOT NULL
              THEN 25 ELSE 0 END) AS pts_unusual_location,

        (CASE WHEN h.login_hour < 6 OR h.login_hour >= 22 THEN 10 ELSE 0 END) AS pts_after_hours,
        (CASE WHEN h.failures_same_day >= 5 THEN 30 ELSE 0 END) AS pts_many_failures,

        -- Tuning note: sensitive app access counts as "risky context" if it's on
        -- a new device/location, OR if the account just reactivated after 60+ days
        -- dormant (even on a familiar device/location — the anomaly is the timing).
        -- Excludes first-ever events for the same cold-start reason as above.
        (CASE WHEN h.sensitivity_level = 'high'
                  AND h.days_since_last_login IS NOT NULL
                  AND (NOT h.device_seen_before
                       OR NOT h.location_seen_before
                       OR h.days_since_last_login >= 60)
              THEN 15 ELSE 0 END) AS pts_sensitive_app_risky_context,

        -- Layer 2: Behavioral (dormancy reactivation)
        (CASE WHEN h.days_since_last_login >= 60 THEN 35 ELSE 0 END) AS pts_dormant_reactivation,

        -- Layer 3: Impossible travel
        (CASE WHEN COALESCE(tf.impossible_travel_flag, FALSE) THEN 40 ELSE 0 END) AS pts_impossible_travel,

        h.device_seen_before,
        h.location_seen_before,
        h.days_since_last_login,
        h.failures_same_day,
        tf.impossible_travel_flag,
        tf.distance_km,
        tf.hours_since_prev,
        tf.prev_city

    FROM history_check h
    LEFT JOIN travel_flagged tf ON h.event_id = tf.event_id
)

SELECT
    event_id,
    username,
    device_fingerprint,
    city,
    country,
    app_name,
    sensitivity_level,
    event_timestamp,
    login_status,

    (pts_failed_login + pts_new_device + pts_unusual_location + pts_after_hours +
     pts_many_failures + pts_sensitive_app_risky_context +
     pts_dormant_reactivation + pts_impossible_travel) AS composite_score,

    CASE
        WHEN (pts_failed_login + pts_new_device + pts_unusual_location + pts_after_hours +
              pts_many_failures + pts_sensitive_app_risky_context +
              pts_dormant_reactivation + pts_impossible_travel) >= 80 THEN 'CRITICAL'
        WHEN (pts_failed_login + pts_new_device + pts_unusual_location + pts_after_hours +
              pts_many_failures + pts_sensitive_app_risky_context +
              pts_dormant_reactivation + pts_impossible_travel) >= 50 THEN 'HIGH'
        WHEN (pts_failed_login + pts_new_device + pts_unusual_location + pts_after_hours +
              pts_many_failures + pts_sensitive_app_risky_context +
              pts_dormant_reactivation + pts_impossible_travel) >= 25 THEN 'MEDIUM'
        ELSE 'LOW'
    END AS risk_tier,

    -- Individual point breakdown (useful for debugging / the priority queue reasons)
    pts_failed_login,
    pts_new_device,
    pts_unusual_location,
    pts_after_hours,
    pts_many_failures,
    pts_sensitive_app_risky_context,
    pts_dormant_reactivation,
    pts_impossible_travel,

    device_seen_before,
    location_seen_before,
    days_since_last_login,
    failures_same_day,
    impossible_travel_flag,
    distance_km,
    hours_since_prev,
    prev_city

FROM scored;