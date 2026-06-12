# Data

## Source

Spanish-language news headlines from public **Google News RSS feeds**
(`hl=es-419`, `gl=CL`), one feed per editorial section. The section of the feed
provides the classification label (weak supervision — no manual annotation):

| label | Google News topic |
|---|---|
| nacional | NATION |
| economia | BUSINESS |
| tecnologia | TECHNOLOGY |
| deportes | SPORTS |
| salud | HEALTH |
| ciencia | SCIENCE |

## What is stored

Only the headline text plus minimal metadata per record: `label`, `source`
(original outlet), `published`, `link` (back to the original coverage) and
`fetched_at`. **No article bodies are stored or redistributed.** The snapshot
exists for reproducibility in an educational/research context; copyright of each
headline remains with its publisher.

## Files

- `raw/headlines_snapshot.jsonl` — committed snapshot, fetched **2026-06-12 UTC**:
  360 records (347 unique after normalization/dedup).
- `processed/` — `train.csv` / `test.csv`, regenerated locally by
  `python -m src.build_dataset` (gitignored).

## Refresh

`python -m src.fetch_data` rewrites the snapshot with current headlines. Class
balance shifts with the news cycle (e.g. `economia` was the smallest section at
fetch time), which is why `build_dataset` enforces a minimum per-class count and
the models use balanced class weights.
