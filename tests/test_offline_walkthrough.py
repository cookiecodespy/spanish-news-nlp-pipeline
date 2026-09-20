"""One offline smoke across the real local ingestion-to-evaluation contracts."""

import json
import subprocess
import sys
from pathlib import Path

from examples.offline_walkthrough import run_walkthrough


def test_walkthrough_runs_actual_normalizer_and_grounding(tmp_path):
    result = run_walkthrough(tmp_path)

    assert result["type"] == "synthetic_offline_walkthrough"
    assert result["real_publication"] is False
    assert result["live_discovery_or_fetch"] is False
    assert result["model_or_jev_calls"] == 0
    assert (tmp_path / "state.sqlite3").is_file()
    assert result["citation_integrity"] == "VALID"
    assert result["candidate_status"] == "UNREVIEWED"
    assert result["semantic_support"] == "HUMAN_LABELED_NOT_VERIFIED"
    assert result["synthetic_supported_claim_precision"] == {
        "numerator": 1, "denominator": 1, "value": 1.0,
    }
    assert len(result["raw_sha256"]) == 64
    assert len(result["normalized_sha256"]) == 64
    assert result["bundle_id"].startswith("eb-")
    assert result["request_id"].startswith("er-")


def test_walkthrough_cli_prints_json_and_cleans_temporary_state():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "examples.offline_walkthrough"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    payload = json.loads(result.stdout)
    assert payload["type"] == "synthetic_offline_walkthrough"
    assert payload["candidate_status"] == "UNREVIEWED"
    assert payload["model_or_jev_calls"] == 0
    assert result.stderr == ""
