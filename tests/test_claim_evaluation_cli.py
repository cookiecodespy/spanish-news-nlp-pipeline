"""Offline CLI contract tests: stable text/JSON output, nonzero failures."""

import json
import sys

import pytest

from research_pipeline import claim_evaluation


def test_cli_json_and_human_output(monkeypatch, capsys, tmp_path):
    payload = {
        "ok": True, "request_id": "er-synthetic", "candidate_count": 1,
        "verdict_counts": {"supported": 1, "partially_supported": 0,
                           "unsupported": 0, "unassessable": 0},
        "supported_claim_precision": {"numerator": 1, "denominator": 1, "value": 1.0},
        "unsupported_claim_rate": {"numerator": 0, "denominator": 1, "value": 0.0},
        "finding_coverage": {"numerator": 0, "denominator": 0, "value": None},
        "abstention": "NOT_APPLICABLE",
    }
    monkeypatch.setattr(claim_evaluation, "_read_json", lambda path: {})
    monkeypatch.setattr(claim_evaluation, "evaluate_case", lambda *args, **kwargs: payload)
    files = [str(tmp_path / name) for name in ("bundle.json", "request.json", "response.json", "review.json")]
    monkeypatch.setattr(sys, "argv", ["claim_evaluation", *files, "--format", "json"])
    assert claim_evaluation.main() == 0
    assert json.loads(capsys.readouterr().out)["finding_coverage"]["value"] is None
    monkeypatch.setattr(sys, "argv", ["claim_evaluation", *files])
    assert claim_evaluation.main() == 0
    output = capsys.readouterr().out
    assert "structural ACCEPTED" in output
    assert "0/0 (UNDEFINED)" in output


def test_cli_failure_exits_nonzero_without_partial_metrics(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(claim_evaluation, "_read_json", lambda path: {})

    def reject(*args, **kwargs):
        raise claim_evaluation.EvaluationError("missing human review")

    monkeypatch.setattr(claim_evaluation, "evaluate_case", reject)
    files = [str(tmp_path / name) for name in ("bundle.json", "request.json", "response.json", "review.json")]
    monkeypatch.setattr(sys, "argv", ["claim_evaluation", *files, "--format", "json"])
    with pytest.raises(SystemExit) as exc:
        claim_evaluation.main()
    assert exc.value.code == 1
    streams = capsys.readouterr()
    assert streams.out == ""
    assert "missing human review" in streams.err
