#!/usr/bin/env bash
# End-to-end pipeline: fetch -> dataset -> train -> evaluate.
# SKIP_FETCH=1 ./run_all.sh reuses the committed snapshot (no network needed).
set -euo pipefail

if [ "${SKIP_FETCH:-0}" != "1" ]; then
  python -m src.fetch_data
fi
python -m src.build_dataset
python -m src.train_baseline
python -m src.evaluate
