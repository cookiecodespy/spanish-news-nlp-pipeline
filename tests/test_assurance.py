import json
from pathlib import Path
from types import SimpleNamespace

import research_pipeline.assurance as assurance
from research_pipeline.assurance import doctor, status, verify_live
from research_pipeline.discovery_state import (
    connect_state,
    record_failure,
    record_success as record_discovery_success,
    start_run,
)
from research_pipeline.ingestion_state import record_success as record_ingestion_success
from research_pipeline.normalization_state import (
    record_success as record_normalization_success,
)


REGISTRY_PATH = Path("sources/registry.json")


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None, encoding="utf-8"):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.encoding = encoding
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self):
        self.closed = True


def fake_get_sequence(responses, seen):
    queue = list(responses)

    def fake_get(url, **kwargs):
        seen.append(url)
        if not queue:
            raise AssertionError("unexpected extra HTTP request")
        return queue.pop(0)

    return fake_get


def test_doctor_passes_with_valid_registry_and_uncreated_state(tmp_path):
    payload = doctor(
        registry_path=REGISTRY_PATH,
        state_path=tmp_path / "state" / "discovery.sqlite3",
    )

    assert payload["ok"] is True
    assert {item["name"] for item in payload["checks"]} == {
        "registry",
        "state",
        "entrypoints",
        "normalizer",
    }
    assert all(item["status"] == "PASS" for item in payload["checks"])


def test_doctor_reports_wrong_normalizer_version(monkeypatch, tmp_path):
    monkeypatch.setattr(assurance, "package_version", lambda _: "9.9.9")

    payload = doctor(
        registry_path=REGISTRY_PATH,
        state_path=tmp_path / "state" / "discovery.sqlite3",
    )

    normalizer = next(item for item in payload["checks"] if item["name"] == "normalizer")
    assert payload["ok"] is False
    assert normalizer["status"] == "FAIL"
    assert "expected 2.2.0" in normalizer["detail"]


def test_doctor_reports_invalid_registry_without_network(tmp_path):
    bad_registry = tmp_path / "bad.json"
    bad_registry.write_text(
        json.dumps({"schema_version": 1, "default": "allow", "sources": []}),
        encoding="utf-8",
    )

    payload = doctor(
        registry_path=bad_registry,
        state_path=tmp_path / "discovery.sqlite3",
    )

    assert payload["ok"] is False
    registry_check = next(item for item in payload["checks"] if item["name"] == "registry")
    assert registry_check["status"] == "FAIL"


def test_status_is_useful_before_state_database_exists(tmp_path):
    payload = status(
        registry_path=REGISTRY_PATH,
        state_path=tmp_path / "missing.sqlite3",
    )

    assert payload["ok"] is True
    assert payload["state_exists"] is False
    assert payload["sources"]
    assert all(item["status"] == "NEVER_RUN" for item in payload["sources"])
    assert all(
        item["ingestion"]["status"] == "NOT_INITIALIZED"
        for item in payload["sources"]
    )
    assert all(
        item["normalization"]["status"] == "NOT_INITIALIZED"
        for item in payload["sources"]
    )


def test_status_surfaces_latest_failure_without_sqlite_inspection(tmp_path):
    state_path = tmp_path / "discovery.sqlite3"
    connection = connect_state(state_path)
    try:
        run_id = start_run(
            connection,
            "anthropic-engineering",
            started_at="2026-09-15T00:00:00+00:00",
        )
        record_failure(
            connection,
            run_id,
            "simulated failure",
            finished_at="2026-09-15T00:00:05+00:00",
        )
    finally:
        connection.close()

    payload = status(registry_path=REGISTRY_PATH, state_path=state_path)
    anthropic = next(
        item for item in payload["sources"] if item["source_id"] == "anthropic-engineering"
    )

    assert anthropic["status"] == "ERROR"
    assert anthropic["run_id"] == run_id
    assert anthropic["error"] == "simulated failure"
    assert anthropic["ingestion"]["status"] == "NOT_INITIALIZED"
    assert anthropic["normalization"]["status"] == "NOT_INITIALIZED"


def test_status_surfaces_ingestion_and_normalization_without_sqlite_inspection(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    requested_url = "https://www.anthropic.com/engineering/example"
    raw_sha = "a" * 64
    normalized_sha = "b" * 64
    connection = connect_state(state_path)
    try:
        run_id = start_run(
            connection,
            "anthropic-engineering",
            started_at="2026-09-15T01:00:00+00:00",
        )
        record_discovery_success(
            connection,
            run_id,
            [
                SimpleNamespace(
                    entrypoint="https://www.anthropic.com/engineering",
                    candidates=[requested_url],
                )
            ],
            seen_at="2026-09-15T01:00:01+00:00",
        )
        raw = record_ingestion_success(
            connection,
            source_id="anthropic-engineering",
            requested_url=requested_url,
            final_url=requested_url,
            content_type="text/html",
            bytes_read=123,
            sha256=raw_sha,
            object_path=f"objects/sha256/aa/{raw_sha}",
            fetched_at="2026-09-15T01:00:02+00:00",
        )
        normalized = record_normalization_success(
            connection,
            source_id="anthropic-engineering",
            requested_url=requested_url,
            ingestion_observation_id=raw.observation_id,
            raw_sha256=raw_sha,
            extractor_name="trafilatura",
            extractor_version="2.2.0",
            normalized_sha256=normalized_sha,
            artifact_path=f"normalized/sha256/bb/{normalized_sha}.json",
            title="Example research article",
            block_count=3,
            char_count=420,
            normalized_at="2026-09-15T01:00:03+00:00",
        )
    finally:
        connection.close()

    payload = status(registry_path=REGISTRY_PATH, state_path=state_path)
    anthropic = next(
        item for item in payload["sources"] if item["source_id"] == "anthropic-engineering"
    )

    # Existing top-level fields remain discovery-compatible.
    assert anthropic["status"] == "SUCCESS"
    assert anthropic["run_id"] == run_id
    assert anthropic["candidate_count"] == 1

    ingestion = anthropic["ingestion"]
    assert ingestion["status"] == "SUCCESS"
    assert ingestion["observation_id"] == raw.observation_id
    assert ingestion["classification"] == "NEW"
    assert ingestion["requested_url"] == requested_url
    assert ingestion["sha256"] == raw_sha

    normalization = anthropic["normalization"]
    assert normalization["status"] == "SUCCESS"
    assert normalization["observation_id"] == normalized.observation_id
    assert normalization["classification"] == "NEW"
    assert normalization["requested_url"] == requested_url
    assert normalization["normalized_sha256"] == normalized_sha
    assert normalization["title"] == "Example research article"
    assert normalization["extractor"] == {"name": "trafilatura", "version": "2.2.0"}


def test_verify_live_reuses_policy_and_reports_pass_with_mocked_http():
    seen = []
    fake_get = fake_get_sequence(
        [
            FakeResponse(
                body=b"User-agent: *\nAllow: /\n",
                headers={"Content-Type": "text/plain"},
            ),
            FakeResponse(
                body=b'<a href="https://www.anthropic.com/engineering/example">example</a>',
                headers={"Content-Type": "text/html"},
            ),
        ],
        seen,
    )

    payload = verify_live(
        registry_path=REGISTRY_PATH,
        source_id="anthropic-engineering",
        delay_s=0,
        request_get=fake_get,
        sleep_fn=lambda _: None,
    )

    assert payload["ok"] is True
    assert payload["status"] == "PASS"
    assert payload["sources"][0]["candidate_count"] == 1
    assert seen == [
        "https://www.anthropic.com/robots.txt",
        "https://www.anthropic.com/engineering",
    ]


def test_verify_live_reports_robots_block_as_blocked():
    seen = []
    fake_get = fake_get_sequence(
        [
            FakeResponse(
                body=b"User-agent: *\nDisallow: /engineering\n",
                headers={"Content-Type": "text/plain"},
            )
        ],
        seen,
    )

    payload = verify_live(
        registry_path=REGISTRY_PATH,
        source_id="anthropic-engineering",
        delay_s=0,
        request_get=fake_get,
        sleep_fn=lambda _: None,
    )

    assert payload["ok"] is False
    assert payload["status"] == "BLOCKED"
    assert payload["sources"][0]["status"] == "BLOCKED"
    assert seen == ["https://www.anthropic.com/robots.txt"]
