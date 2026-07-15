-- 03_priority_queue.sql
-- CIPHER: Priority Investigation Queue
-- Top 20 highest-risk login events, ranked, with human-readable reasons.

SELECT
    RANK() OVER (ORDER BY composite_score DESC) AS priority_rank,
    username,
    device_fingerprint,
    city || ', ' || country AS location,
    app_name,
    event_timestamp,
    login_status,
    composite_score,
    risk_tier,

    -- Build a plain-English reasons string from whichever rules fired
    TRIM(BOTH ', ' FROM
        CONCAT(
            CASE WHEN pts_failed_login > 0 THEN 'Failed login attempt, ' ELSE '' END,
            CASE WHEN pts_new_device > 0 THEN 'New device never used by this user, ' ELSE '' END,
            CASE WHEN pts_unusual_location > 0 THEN 'Location never used by this user, ' ELSE '' END,
            CASE WHEN pts_after_hours > 0 THEN 'After-hours login, ' ELSE '' END,
            CASE WHEN pts_many_failures > 0 THEN 'Five or more failures same day, ' ELSE '' END,
            CASE WHEN pts_sensitive_app_risky_context > 0 THEN 'Sensitive app accessed in risky context, ' ELSE '' END,
            CASE WHEN pts_dormant_reactivation > 0
                 THEN 'Dormant account reactivated after ' || ROUND(days_since_last_login) || ' days, '
                 ELSE '' END,
            CASE WHEN pts_impossible_travel > 0
                 THEN 'Impossible travel: ' || ROUND(distance_km) || ' km from ' || prev_city ||
                      ' in ' || ROUND(hours_since_prev, 1) || ' hours, '
                 ELSE '' END
        )
    ) AS reasons

FROM risk_scores
ORDER BY composite_score DESC
LIMIT 20;