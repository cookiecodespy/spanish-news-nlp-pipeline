import json
from pathlib import Path

from research_pipeline.assurance import doctor, status, verify_live
from research_pipeline.discovery_state import connect_state, record_failure, start_run


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
    }
    assert all(item["status"] == "PASS" for item in payload["checks"])


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


def test_status_surfaces_latest_failure_without_sqlite_inspection(tmp_path):
    state_path = tmp_path / "discovery.sqlite3"
    connection = connect_state(state_path)
    try:
        run_id = start_run(connection, "anthropic-engineering", started_at="2026-09-15T00:00:00+00:00")
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
