import json
import shutil
import urllib.error
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts import probe_geoapify
from scripts.probe_geoapify import (
    HanoiTransport,
    build_requests,
    classify_failure,
    run_probes,
)

# Self-hosted runners may lack git on PATH; these tests shell out to `git init`.
requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


@pytest.fixture(autouse=True)
def isolated_probe_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEOAPIFY_API_KEY", raising=False)

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("unit fixtures must not use the network")

    monkeypatch.setattr(probe_geoapify.urllib.request, "build_opener", refuse_network)


def fixture_results(operation, payload):
    class Transport:
        def request(self, request, _key, timeout=10.0):
            return (200, payload) if request.operation == operation else (599, {})

    return next(item for item in run_probes(Transport(), live=False) if item["operation"] == operation)


def test_requests_match_six_public_hanoi_capabilities():
    requests = build_requests()
    assert [request.operation for request in requests] == [
        "geocode",
        "reverse_geocode",
        "routing",
        "map_matching",
        "map_style",
        "mcp_tools",
    ]
    assert requests[0].parameters == {"text": "Hoan Kiem Lake, Hanoi, Vietnam", "filter": "countrycode:vn", "limit": 1}
    assert requests[2].parameters["waypoints"] == "21.0278,105.8342|21.0285,105.8443"
    assert requests[3].body["waypoints"][0]["location"] == [105.8342, 21.0278]


def test_offline_failures_are_allowlisted_and_never_include_transport_details():
    results = run_probes(HanoiTransport(failure_mode=True), live=False)
    assert len(results) == 6
    assert {result["failure"] for result in results} == {
        "unauthorized",
        "forbidden",
        "rate_limited",
        "malformed_response",
        "timeout",
        "provider_unavailable",
    }
    serialized = json.dumps(results)
    assert "api.geoapify.com" not in serialized
    assert "secret" not in serialized.lower()
    assert all(set(result) <= {"operation", "failure", "http_status"} for result in results)


def test_failure_classifier_collapses_unknown_provider_errors():
    assert classify_failure(401) == "unauthorized"
    assert classify_failure(403) == "forbidden"
    assert classify_failure(429) == "rate_limited"
    assert classify_failure(599) == "provider_unavailable"
    assert classify_failure(None, malformed=True) == "malformed_response"
    assert classify_failure(None, timed_out=True) == "timeout"


def test_request_shapes_include_exact_methods_endpoints_and_bodies():
    requests = build_requests()
    assert [(r.method, r.endpoint) for r in requests] == [
        ("GET", "https://api.geoapify.com/v1/geocode/search"),
        ("GET", "https://api.geoapify.com/v1/geocode/reverse"),
        ("GET", "https://api.geoapify.com/v1/routing"),
        ("POST", "https://api.geoapify.com/v1/mapmatching"),
        ("GET", "https://maps.geoapify.com/v1/styles/osm-bright/style.json"),
        ("POST", "https://api.geoapify.com/v1/mcp"),
    ]
    assert requests[3].body["mode"] == "drive"
    assert requests[5].body == {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def test_failure_payload_and_transport_details_are_never_returned():
    class PoisonTransport(HanoiTransport):
        def request(self, request, key, timeout=10.0):
            return 500, {
                "error": "CANARY_BODY",
                "url": "https://evil.invalid/?apiKey=CANARY_KEY",
                "headers": {"x-api-key": "CANARY_KEY"},
            }

    results = run_probes(PoisonTransport(), live=False)
    assert "CANARY" not in json.dumps(results)
    assert all(set(result) <= {"operation", "failure", "http_status"} for result in results)


def test_offline_probe_never_reads_or_sends_a_key():
    class CaptureTransport(HanoiTransport):
        def __init__(self):
            super().__init__()
            self.keys = []

        def request(self, request, key, timeout=10.0):
            self.keys.append(key)
            return 200, {"features": []} if request.operation != "map_style" else {"version": 8}

    transport = CaptureTransport()
    run_probes(transport, live=False)
    assert transport.keys == [None] * 6


def test_entire_probe_requests_match_baseline_artifact():
    baseline = Path(__file__).resolve().parents[3] / "docs/testing/artifacts/geoapify/capabilities-2026-10-08.json"
    expected = json.loads(baseline.read_text())["requests"]
    actual = [{k: v for k, v in asdict(request).items() if v is not None} for request in build_requests()]
    assert actual == expected


def test_live_missing_key_never_sends_requests(monkeypatch):
    monkeypatch.setattr(probe_geoapify, "_read_key", lambda: "")

    class NoHTTP:
        def request(self, *_a, **_kw):
            raise AssertionError("missing key must not use HTTP")

    assert run_probes(NoHTTP(), live=True) == [
        {"operation": operation, "failure": "missing_key"} for operation in probe_geoapify.CAPABILITIES
    ]


def test_live_attempts_are_six_sequential_bounded_calls(monkeypatch):
    monkeypatch.setattr(probe_geoapify, "_read_key", lambda: "fixture-only")
    sleeps = []
    calls = []
    monkeypatch.setattr(probe_geoapify.time, "sleep", sleeps.append)

    class Transport:
        def request(self, request, _key, timeout=10.0):
            calls.append((request.operation, timeout))
            return 429, {"error": "CANARY"}

    results = run_probes(Transport(), live=True)
    assert calls == [(operation, 10.0) for operation in probe_geoapify.CAPABILITIES]
    assert sleeps == [0.21] * 6
    assert all(item["failure"] == "rate_limited" for item in results)


def test_success_summaries_preserve_safe_provider_metrics_and_match_status():
    class Transport:
        def request(self, request, _key, timeout=10.0):
            if request.operation == "map_style":
                return 200, {"version": 8, "sources": {"tiles": {"url": "CANARY"}}, "layers": [{}]}
            if request.operation == "mcp_tools":
                return 200, {
                    "jsonrpc": "2.0",
                    "result": {"tools": [{"name": "CANARY", "description": "CANARY"}]},
                    "content": "CANARY",
                }
            geometry = "Point" if request.operation in {"geocode", "reverse_geocode"} else "MultiLineString"
            coordinates = [105.8342, 21.0278] if geometry == "Point" else [[[105.8342, 21.0278], [105.8352, 21.028]]]
            return 200, {
                "features": [
                    {
                        "geometry": {"type": geometry, "coordinates": coordinates},
                        "properties": {
                            "distance": 1317,
                            "time": 87.581,
                            "mode": "drive",
                            "traffic": "free_flow",
                            "country_code": "vn",
                            "waypoints": [
                                {"match_type": "matched"},
                                {"match_type": "unmatched"},
                                {"match_type": "CANARY"},
                            ],
                            "error": "CANARY",
                            "url": "CANARY",
                        },
                    }
                ]
            }

    results = run_probes(Transport(), live=False)
    assert results[2]["distance"] == 1317
    assert results[2]["time"] == 87.581
    assert results[2]["mode"] == "drive"
    assert results[2]["traffic"] == "free_flow"
    assert results[3]["match_types"] == ["matched", "unmatched", "unknown"]
    assert "CANARY" not in json.dumps(results)


def test_unexpected_provider_exception_never_escapes_with_private_text():
    class Transport:
        def request(self, *_a, **_kw):
            raise TypeError("CANARY provider URL and body")

    results = run_probes(Transport(), live=False)
    assert len(results) == 6
    assert "CANARY" not in json.dumps(results)


def test_cli_fixture_metadata_does_not_claim_a_live_attempt(tmp_path, capsys):
    path = tmp_path / "failures.json"
    assert probe_geoapify.main(["--offline-failures", "--output", str(path)]) == 0
    record = json.loads(path.read_text())
    assert record["evidence_class"] == "offline_failure_fixture"
    assert all("Live attempt was blocked" not in item for item in record["limitations"])
    assert capsys.readouterr().out == ""


def test_success_summaries_reject_poisoned_shape_values_and_provider_error_payloads():
    class PoisonTransport(HanoiTransport):
        def request(self, request, key, timeout=10.0):
            if request.operation == "map_style":
                return 200, {"version": 8, "sources": {"https://evil.invalid/CANARY": {}}, "layers": [{"id": "CANARY"}]}
            if request.operation == "mcp_tools":
                return 200, {"error": {"message": "CANARY"}}
            return 200, {"features": [{"geometry": {"type": "CANARY"}, "properties": {"distance": "CANARY"}}]}

    results = run_probes(PoisonTransport(), live=False)
    serialized = json.dumps(results)
    assert "CANARY" not in serialized
    assert all(result.get("failure") == "malformed_response" for result in results[:4])
    assert results[4]["source_count"] == 1
    assert results[5]["failure"] == "malformed_response"


def test_malformed_json_transport_is_sanitized():
    class BrokenTransport(HanoiTransport):
        def request(self, request, key, timeout=10.0):
            raise ValueError("secret body CANARY")

    results = run_probes(BrokenTransport(), live=False)
    assert all(result["failure"] == "malformed_response" for result in results)
    assert "CANARY" not in json.dumps(results)


@pytest.mark.parametrize("operation", ["geocode", "reverse_geocode", "routing", "map_matching"])
@pytest.mark.parametrize("features", [[], [None], ["CANARY"], [{"geometry": {"type": "Point"}}]])
def test_empty_or_malformed_features_are_never_successful(operation, features):
    assert fixture_results(operation, {"features": features}) == {
        "operation": operation,
        "failure": "malformed_response",
    }


@pytest.mark.parametrize(
    ("operation", "geometry"),
    [
        ("geocode", {"type": "LineString", "coordinates": [[105, 21], [106, 22]]}),
        ("reverse_geocode", {"type": "MultiLineString", "coordinates": [[[105, 21], [106, 22]]]}),
        ("routing", {"type": "Point", "coordinates": [105, 21]}),
        ("map_matching", {"type": "LineString", "coordinates": [[105, 21], [106, 22]]}),
        ("geocode", {"type": "Point", "coordinates": []}),
        ("geocode", {"type": "Point", "coordinates": [181, 21]}),
        ("geocode", {"type": "Point", "coordinates": [105, -91]}),
        ("geocode", {"type": "Point", "coordinates": [True, 21]}),
        ("geocode", {"type": "Point", "coordinates": [float("nan"), 21]}),
        ("routing", {"type": "LineString", "coordinates": [[105, 21]]}),
        ("routing", {"type": "LineString", "coordinates": [[105, 21], [float("inf"), 22]]}),
        ("routing", {"type": "MultiLineString", "coordinates": []}),
        ("map_matching", {"type": "MultiLineString", "coordinates": [[]]}),
        ("map_matching", {"type": ["CANARY"], "coordinates": []}),
    ],
)
def test_geometries_must_be_valid_for_each_capability(operation, geometry):
    result = fixture_results(operation, {"features": [{"geometry": geometry}]})
    assert result == {"operation": operation, "failure": "malformed_response"}
    assert "CANARY" not in json.dumps(result)


@pytest.mark.parametrize(
    ("operation", "geometry"),
    [
        ("geocode", {"type": "Point", "coordinates": [105.8342, 21.0278]}),
        ("reverse_geocode", {"type": "Point", "coordinates": [105.8342, 21.0278, 10]}),
        ("routing", {"type": "LineString", "coordinates": [[105.8342, 21.0278], [105.8352, 21.028]]}),
        ("routing", {"type": "MultiLineString", "coordinates": [[[105.8342, 21.0278], [105.8352, 21.028]]]}),
        ("map_matching", {"type": "MultiLineString", "coordinates": [[[105.8342, 21.0278], [105.8352, 21.028]]]}),
    ],
)
def test_valid_geometries_produce_only_sanitized_counts_and_type(operation, geometry):
    assert fixture_results(operation, {"features": [{"geometry": geometry, "CANARY": "CANARY"}]}) == {
        "operation": operation,
        "http_status": 200,
        "feature_count": 1,
        "geometry_type": geometry["type"],
    }


def test_each_feature_must_be_valid_before_reporting_success():
    result = fixture_results(
        "routing",
        {
            "features": [
                {"geometry": {"type": "LineString", "coordinates": [[105, 21], [106, 22]]}},
                {"geometry": {"type": "Point", "coordinates": [105, 21]}},
            ]
        },
    )
    assert result == {"operation": "routing", "failure": "malformed_response"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"version": "CANARY", "sources": {"tiles": {}}, "layers": [{}]},
        {"version": 9, "sources": {"tiles": {}}, "layers": [{}]},
        {"version": 8.0, "sources": {"tiles": {}}, "layers": [{}]},
        {"version": 8, "sources": [], "layers": [{}]},
        {"version": 8, "sources": {}, "layers": [{}]},
        {"version": 8, "sources": {"tiles": {}}, "layers": []},
        {"version": 8, "sources": {"tiles": {}}, "layers": "CANARY"},
        {"version": 8, "sources": {"tiles": "CANARY"}, "layers": [{}]},
        {"version": 8, "sources": {"tiles": {}}, "layers": ["CANARY"]},
    ],
)
def test_style_requires_version_eight_sources_and_layers(payload):
    result = fixture_results("map_style", payload)
    assert result == {"operation": "map_style", "failure": "malformed_response"}
    assert "CANARY" not in json.dumps(result)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"result": {"tools": [{}]}},
        {"jsonrpc": "CANARY", "result": {"tools": [{}]}},
        {"jsonrpc": "1.0", "result": {"tools": [{}]}},
        {"jsonrpc": "2.0", "result": []},
        {"jsonrpc": "2.0", "result": {}},
        {"jsonrpc": "2.0", "result": {"tools": []}},
        {"jsonrpc": "2.0", "result": {"tools": "CANARY"}},
        {"jsonrpc": "2.0", "result": {"tools": ["CANARY"]}},
        {"jsonrpc": "2.0", "result": {"tools": [{}, None]}},
        {"jsonrpc": "2.0", "result": {"tools": [{}]}, "error": {"message": "CANARY"}},
    ],
)
def test_mcp_requires_jsonrpc_two_nonempty_tool_dicts_without_error(payload):
    result = fixture_results("mcp_tools", payload)
    assert result == {"operation": "mcp_tools", "failure": "malformed_response"}
    assert "CANARY" not in json.dumps(result)


@pytest.mark.parametrize(
    ("operation", "payload", "summary"),
    [
        (
            "map_style",
            {"version": 8, "sources": {"CANARY": {}}, "layers": [{"id": "CANARY"}]},
            {"style_version": 8, "source_count": 1, "layer_count": 1},
        ),
        ("mcp_tools", {"jsonrpc": "2.0", "result": {"tools": [{"name": "CANARY"}]}}, {"tool_count": 1}),
    ],
)
def test_valid_style_and_mcp_produce_only_sanitized_counts(operation, payload, summary):
    assert fixture_results(operation, payload) == {"operation": operation, "http_status": 200, **summary}


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (TimeoutError("CANARY timeout"), "timeout"),
        (urllib.error.URLError(TimeoutError("CANARY timeout")), "timeout"),
        (urllib.error.URLError("CANARY private URL"), "provider_unavailable"),
        (OSError("CANARY socket"), "provider_unavailable"),
        (ValueError("CANARY payload"), "malformed_response"),
        (RuntimeError("CANARY payload"), "malformed_response"),
        (TypeError("CANARY payload"), "malformed_response"),
        (AttributeError("CANARY payload"), "malformed_response"),
    ],
)
def test_provider_exceptions_are_classified_without_leaking(error, failure, capsys):
    class Transport:
        def request(self, *_args, **_kwargs):
            raise error

    results = run_probes(Transport(), live=False)
    assert results == [{"operation": operation, "failure": failure} for operation in probe_geoapify.CAPABILITIES]
    assert "CANARY" not in json.dumps(results)
    assert capsys.readouterr() == ("", "")


def test_environment_key_precedes_env_file_without_opening_any_file(monkeypatch, capsys):
    monkeypatch.setenv("GEOAPIFY_API_KEY", "CANARY_ENV_KEY")
    keys = []
    monkeypatch.setattr(probe_geoapify.time, "sleep", lambda _seconds: None)

    def refuse_files(*_args, **_kwargs):
        raise AssertionError("environment key must take precedence without reading files")

    monkeypatch.setattr(Path, "is_file", refuse_files)
    monkeypatch.setattr(Path, "open", refuse_files)

    class Transport:
        def request(self, _request, key, timeout=10.0):
            keys.append(key)
            return 429, {}

    results = run_probes(Transport(), live=True)
    assert keys == ["CANARY_ENV_KEY"] * 6
    assert all(item["failure"] == "rate_limited" for item in results)
    assert "CANARY" not in json.dumps(results)
    assert capsys.readouterr() == ("", "")


def test_live_run_reads_key_only_once(monkeypatch):
    reads = []
    keys = []

    def fixture_key(env_file=Path(".env")):
        reads.append(env_file)
        return "fixture-only"

    monkeypatch.setattr(probe_geoapify, "_read_key", fixture_key)
    monkeypatch.setattr(probe_geoapify.time, "sleep", lambda _seconds: None)

    class Transport:
        def request(self, _request, key, timeout=10.0):
            keys.append(key)
            return 429, {}

    run_probes(Transport(), live=True)
    assert reads == [Path(".env")]
    assert keys == ["fixture-only"] * 6


@requires_git
@pytest.mark.parametrize("explicit_env_file", [False, True])
def test_cli_reads_portable_dotenv_file_and_returns_live_failure(monkeypatch, tmp_path, capsys, explicit_env_file):
    import subprocess

    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    (tmp_path / ".gitignore").write_text(".env\nprobe.env\n")
    env_file = tmp_path / ("probe.env" if explicit_env_file else ".env")
    env_file.write_text('export GEOAPIFY_API_KEY = "CANARY_FILE_KEY" # fixture\n')
    keys = []
    monkeypatch.setattr(probe_geoapify.time, "sleep", lambda _seconds: None)
    original_is_file = Path.is_file

    def only_fixture_file(path):
        assert not path.is_absolute() or path.is_relative_to(tmp_path), "must not inspect machine-specific env files"
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", only_fixture_file)

    def fixture_request(_transport, _request, key, timeout=10.0):
        keys.append(key)
        return 429, {"error": "CANARY_BODY"}

    monkeypatch.setattr(HanoiTransport, "request", fixture_request)
    argv = ["--live"]
    if explicit_env_file:
        argv.extend(["--env-file", str(env_file)])
    assert probe_geoapify.main(argv) == 1
    assert keys == ["CANARY_FILE_KEY"] * 6
    captured = capsys.readouterr()
    assert "CANARY" not in captured.out + captured.err
    assert captured.err == ""
    assert {item["failure"] for item in json.loads(captured.out)["results"]} == {"rate_limited"}


def test_offline_cli_never_reads_env_file(monkeypatch, tmp_path, capsys):
    def refuse_key(*_args, **_kwargs):
        raise AssertionError("offline fixture must not read credentials")

    monkeypatch.setattr(probe_geoapify, "_read_key", refuse_key)
    assert probe_geoapify.main(["--offline-failures", "--env-file", str(tmp_path / "not-read.env")]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["evidence_class"] == "offline_failure_fixture"
    assert len(record["results"]) == 6


def test_cli_missing_key_exits_nonzero_without_sending_requests(monkeypatch, capsys):
    monkeypatch.setattr(probe_geoapify, "_read_key", lambda: "")
    assert probe_geoapify.main(["--live"]) == 1
    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert record["results"] == [
        {"operation": operation, "failure": "missing_key"} for operation in probe_geoapify.CAPABILITIES
    ]
    assert captured.err == ""


@pytest.mark.parametrize("failed_operation", [None, *probe_geoapify.CAPABILITIES])
def test_cli_exit_reflects_each_validated_capability_without_canary_leaks(monkeypatch, capsys, failed_operation):
    monkeypatch.setenv("GEOAPIFY_API_KEY", "CANARY_KEY")
    monkeypatch.setattr(probe_geoapify.time, "sleep", lambda _seconds: None)
    calls = []

    def fixture_request(_transport, request, key, timeout=10.0):
        calls.append(request.operation)
        assert key == "CANARY_KEY"
        if request.operation == failed_operation:
            return 200, {
                "features": [{"geometry": {"type": ["CANARY"]}}],
                "version": "CANARY",
                "jsonrpc": "2.0",
                "result": {"tools": ["CANARY"]},
                "headers": {"x-api-key": "CANARY_KEY"},
                "url": "https://evil.invalid/CANARY_KEY",
            }
        if request.operation == "map_style":
            return 200, {"version": 8, "sources": {"CANARY": {}}, "layers": [{"id": "CANARY"}]}
        if request.operation == "mcp_tools":
            return 200, {"jsonrpc": "2.0", "result": {"tools": [{"name": "CANARY"}]}}
        point = request.operation in ("geocode", "reverse_geocode")
        return 200, {
            "features": [
                {
                    "geometry": {
                        "type": "Point" if point else "MultiLineString",
                        "coordinates": [105, 21] if point else [[[105, 21], [106, 22]]],
                    },
                    "properties": {
                        "distance": "CANARY",
                        "time": float("nan"),
                        "mode": {"CANARY": "CANARY"},
                        "traffic": ["CANARY"],
                        "country_code": "CANARY",
                        "waypoints": [{"match_type": ["CANARY"]}, None],
                        "headers": {"x-api-key": "CANARY_KEY"},
                    },
                }
            ]
        }

    monkeypatch.setattr(HanoiTransport, "request", fixture_request)
    assert probe_geoapify.main(["--live"]) == (1 if failed_operation else 0)
    captured = capsys.readouterr()
    assert "CANARY" not in captured.out + captured.err
    assert "evil.invalid" not in captured.out
    assert captured.err == ""
    record = json.loads(captured.out)
    assert calls == list(probe_geoapify.CAPABILITIES)
    assert [item["operation"] for item in record["results"] if "failure" in item] == (
        [failed_operation] if failed_operation else []
    )


def test_transport_refuses_redirects_without_exposing_private_details(monkeypatch, capsys):
    calls = []

    def fixture_opener(handler):
        class Opener:
            def open(self, request, timeout):
                calls.append(timeout)
                return handler.redirect_request(
                    request, None, 302, "CANARY", {"x-api-key": "CANARY_KEY"}, "https://evil.invalid/CANARY_KEY"
                )

        return Opener()

    monkeypatch.setattr(probe_geoapify.urllib.request, "build_opener", fixture_opener)
    results = run_probes(HanoiTransport(), live=False)
    assert calls == [10.0] * 6
    assert all(item["failure"] == "provider_unavailable" for item in results)
    assert "CANARY" not in json.dumps(results)
    assert capsys.readouterr() == ("", "")


def test_transport_caps_response_size_without_retrying(monkeypatch):
    reads = []
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self, size):
            reads.append(size)
            return b"x" * size

    class Opener:
        def open(self, _request, timeout):
            calls.append(timeout)
            return Response()

    monkeypatch.setattr(probe_geoapify.urllib.request, "build_opener", lambda _handler: Opener())
    results = run_probes(HanoiTransport(), live=False)
    assert reads == [2 * 1024 * 1024 + 1] * 6
    assert calls == [10.0] * 6
    assert all(item["failure"] == "malformed_response" for item in results)


@requires_git
def test_live_probe_refuses_a_credential_file_not_ignored_by_git(monkeypatch, tmp_path):
    import subprocess

    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    env_file = tmp_path / ".env"
    env_file.write_text("GEOAPIFY_API_KEY=CANARY_TRACKED_FILE\n")
    monkeypatch.delenv("GEOAPIFY_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(probe_geoapify.time, "sleep", lambda _seconds: None)

    class Transport:
        def request(self, *_args, **_kwargs):
            calls.append(1)
            return 429, {}

    results = run_probes(Transport(), live=True, env_file=env_file)
    assert calls == []
    assert all(item["failure"] == "missing_key" for item in results)


def test_probe_refuses_credential_file_and_warns_when_git_is_absent(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PATH", "/usr/bin/no-git")
    env_file = tmp_path / ".env"
    env_file.write_text("GEOAPIFY_API_KEY=CANARY_KEY\n")
    monkeypatch.delenv("GEOAPIFY_API_KEY", raising=False)

    assert not probe_geoapify._ignored(env_file)
    err = capsys.readouterr().err
    assert "Unable to verify git ignore status" in err
    assert "refusing credential file" in err
    assert probe_geoapify._read_key(env_file) == ""

    class Transport:
        def request(self, *_args, **_kwargs):
            raise AssertionError("must not send request without key")

    results = run_probes(Transport(), live=True, env_file=env_file)
    assert all(item["failure"] == "missing_key" for item in results)
