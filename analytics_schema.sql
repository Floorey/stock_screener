CREATE SCHEMA IF NOT EXISTS analytics;
CREATE TABLE IF NOT EXISTS analytics.raw_pages (
 id bigserial PRIMARY KEY, source text NOT NULL, request_key text NOT NULL,
 request jsonb NOT NULL, response jsonb NOT NULL, response_sha256 text NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now(), http_status integer NOT NULL DEFAULT 200,
 UNIQUE(source,request_key,response_sha256)
);
CREATE TABLE IF NOT EXISTS analytics.checkpoints (
 job_key text PRIMARY KEY, source text NOT NULL, request jsonb NOT NULL,
 cursor text, status text NOT NULL, row_count bigint NOT NULL DEFAULT 0,
 error text, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analytics.sessions (
 session_date date PRIMARY KEY, opens_at timestamptz NOT NULL, closes_at timestamptz NOT NULL,
 raw_page_id bigint NOT NULL REFERENCES analytics.raw_pages(id)
);
CREATE TABLE IF NOT EXISTS analytics.bars (
 symbol text NOT NULL, timeframe text NOT NULL, feed text NOT NULL, adjustment text NOT NULL,
 event_at timestamptz NOT NULL, available_at timestamptz,
 availability_basis text NOT NULL DEFAULT 'provider historical availability unknown',
 open double precision NOT NULL, high double precision NOT NULL, low double precision NOT NULL,
 close double precision NOT NULL, volume double precision NOT NULL,
 revision_sha256 text NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(),
 last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 raw_page_id bigint NOT NULL REFERENCES analytics.raw_pages(id),
 PRIMARY KEY(symbol,timeframe,feed,adjustment,event_at,revision_sha256),
 CHECK(open>0 AND high>0 AND low>0 AND close>0 AND volume>=0 AND low<=high)
);
CREATE TABLE IF NOT EXISTS analytics.macro_observations (
 series_id text NOT NULL, observation_date date NOT NULL,
 vintage_start date NOT NULL, vintage_end date NOT NULL,
 available_at timestamptz NOT NULL, availability_precision text NOT NULL DEFAULT 'date; conservative next New York midnight',
 value double precision, revision_sha256 text NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now(), last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 raw_page_id bigint NOT NULL REFERENCES analytics.raw_pages(id),
 PRIMARY KEY(series_id,observation_date,vintage_start,revision_sha256)
);
CREATE INDEX IF NOT EXISTS bars_lookup ON analytics.bars(timeframe,feed,adjustment,event_at,symbol);
CREATE INDEX IF NOT EXISTS macro_pit ON analytics.macro_observations(series_id,observation_date,available_at);
ALTER TABLE analytics.bars ADD COLUMN IF NOT EXISTS last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp();
ALTER TABLE analytics.macro_observations ADD COLUMN IF NOT EXISTS last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp();
DROP VIEW IF EXISTS analytics.latest_bars;
CREATE OR REPLACE VIEW analytics.latest_bars AS
 SELECT DISTINCT ON(symbol,timeframe,feed,adjustment,event_at) * FROM analytics.bars
 ORDER BY symbol,timeframe,feed,adjustment,event_at,last_seen_at DESC,raw_page_id DESC;
