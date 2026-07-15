-- 01_create_warehouse.sql
-- CIPHER: Warehouse schema for behavioral risk scoring

CREATE TABLE dim_user (
    user_id         SERIAL PRIMARY KEY,
    username        VARCHAR(50) UNIQUE NOT NULL,
    full_name       VARCHAR(100),
    department      VARCHAR(50),
    role            VARCHAR(50),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE dim_device (
    device_id       SERIAL PRIMARY KEY,
    device_fingerprint VARCHAR(100) UNIQUE NOT NULL,
    device_type     VARCHAR(30),      -- laptop, mobile, tablet
    os              VARCHAR(30),
    first_seen      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE dim_location (
    location_id     SERIAL PRIMARY KEY,
    city            VARCHAR(100),
    country         VARCHAR(100),
    latitude        DECIMAL(9,6),
    longitude       DECIMAL(9,6)
);

CREATE TABLE dim_application (
    application_id  SERIAL PRIMARY KEY,
    app_name        VARCHAR(100) UNIQUE NOT NULL,
    sensitivity_level VARCHAR(20)     -- low, medium, high
);

CREATE TABLE fact_login_events (
    event_id        BIGSERIAL PRIMARY KEY,
    user_id         INT REFERENCES dim_user(user_id),
    device_id       INT REFERENCES dim_device(device_id),
    location_id     INT REFERENCES dim_location(location_id),
    application_id  INT REFERENCES dim_application(application_id),
    event_timestamp TIMESTAMP NOT NULL,
    login_status    VARCHAR(20) NOT NULL,   -- success, failure
    ip_address      VARCHAR(45)
);

-- Indexes to support the scoring engine's window-function lookups
CREATE INDEX idx_fact_user_time ON fact_login_events(user_id, event_timestamp);
CREATE INDEX idx_fact_device ON fact_login_events(device_id);
CREATE INDEX idx_fact_location ON fact_login_events(location_id);
CREATE INDEX idx_fact_status ON fact_login_events(login_status);