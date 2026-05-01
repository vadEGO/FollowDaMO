# Research Agent

**Purpose:** Generate structured research packs for assets that have cleared the signal and tradeability gates.

## Inputs
- `asset_signals` with `research_priority` of `level_2`, `level_3`, or `level_4`
- `asset_tradeability` — check tradeable/research-only status
- `prompts/research_prompt.md`
- `prompts/premortem_prompt.md`
- `config/research_rules.yaml` — minimum requirements and cost controls
- `config/control_policy.yaml` — daily research budget

## Outputs
- New rows in `research_packs` table
- Markdown files saved to `knowledge/research_packs/{symbol}_{date}.md`

## Workflow

### 1. Check daily research budget
Query `pipeline_runs` for today's research runs. If `max_deep_research_per_day` has been reached, downgrade any `level_3` or `level_4` requests to `level_2`. Log the downgrade.

### 2. Check recency
For each candidate, check if a research pack exists in `research_packs` for this asset with `created_at` within the last `min_hours_between_reruns` hours. If so, skip re-research (use the existing pack). This controls LLM cost.

### 3. Level 1 — Signal card
For `level_1` assets: generate a 3-sentence signal card. No deep research.

### 4. Level 2 — Quick research
For `level_2` assets: run the research prompt with a note to focus on minimum requirements only. Target output: 500-800 words.

### 5. Level 3 — Full research pack
For `level_3` assets: run the full research prompt using `prompts/research_prompt.md`. Run the pre-mortem using `prompts/premortem_prompt.md`. Target output: 15 sections, 1500-2500 words.

### 6. Level 4 — Active thesis tracking
Same as level 3, plus:
- Compare against any existing research pack for this asset
- Identify what has changed
- Update the thesis memory in `asset_thesis_scores`

### 7. Validate research pack
After generation:
- Verify all required sections are present for the research level
- Check that claims labelled `[SC]`, `[UK]`, or `[AS]` are not used to increase `viability_score`
- If evidence quality is below "low" threshold: set `final_decision = 'reject'` regardless of score

### 8. Store
Insert into `research_packs`. Save markdown to `knowledge/research_packs/`.

### 9. Log
Insert a row into `pipeline_runs` for this stage.
