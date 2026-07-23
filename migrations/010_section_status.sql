-- 010 — Per-section freshness roll-up for the dashboard.
-- Each analysis "section" (scores, portfolio, council, …) runs on its own
-- cadence via scripts/run_section.py. This table holds ONE row per section with
-- its last run outcome, so the dashboard can show per-section freshness instead
-- of a single global pipeline-sync time that masks a stalled section.
-- Written by scripts/sync_to_supabase.py:sync_section_status() (service role);
-- read by the app via public_section_status.

CREATE TABLE IF NOT EXISTS pipeline_section_status (
  section           text PRIMARY KEY,
  display_name      text,
  status            text NOT NULL,            -- completed | failed | running | skipped
  cadence           text,                     -- daily | hourly | weekly | on_demand
  stale_after_hours numeric,                  -- age past which the section is STALE (from sections.yaml)
  last_run_at       timestamptz,              -- when the section last finished a run
  last_ok_at        timestamptz,              -- when it last completed successfully
  stages            text,                     -- comma-separated stage names in this section
  records_processed integer DEFAULT 0,
  error             text,
  updated_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE pipeline_section_status ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon read section status" ON pipeline_section_status;
CREATE POLICY "anon read section status" ON pipeline_section_status
  FOR SELECT TO anon, authenticated USING (true);

CREATE OR REPLACE VIEW public_section_status AS
SELECT section, display_name, status, cadence, stale_after_hours,
       last_run_at, last_ok_at, stages, records_processed, error, updated_at
FROM pipeline_section_status
ORDER BY section;

GRANT SELECT ON public_section_status TO anon, authenticated;
