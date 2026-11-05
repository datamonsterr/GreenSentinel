"""Compare full policy outputs against actual pre-change code, including mutation boundaries."""

from __future__ import annotations

import json

import pytest

from eval.profile_policy_fallback import load_baseline
from src.rag.store import QdrantPolicyStore


@pytest.mark.parametrize(
    "query,where",
    [
        ("appeal evidence review", None),
        ("delivery cancellation", {"category": "all"}),
        ("đối tác hủy chuyến", None),
        ("", None),
        ("unknownzzword", None),
        ("driver policy", {"category": "delivery"}),
        ("driver", {"category": "nonexistent"}),
    ],
)
def test_complete_results_equal_prechange_method(query, where):
    store = QdrantPolicyStore.__new__(QdrantPolicyStore)
    assert store._fallback_local_search(query, top_k=6, where=where) == load_baseline()(
        store, query, top_k=6, where=where
    )


def test_each_search_reads_current_policy_without_stale_cache(tmp_path, monkeypatch):
    directory = tmp_path / "data/processed"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps([{"slug": "policy", "id": "policy", "title": "Policy", "category": "test"}])
    )
    policy = directory / "policy.md"
    policy.write_text("Policy evidence for driver review is documented in this original paragraph.")
    monkeypatch.chdir(tmp_path)
    store = QdrantPolicyStore.__new__(QdrantPolicyStore)
    first = store._fallback_local_search("driver")
    policy.write_text("Policy evidence for driver review has now changed in this revised paragraph.")
    second = store._fallback_local_search("driver")
    assert first and second and first[0]["content"] != second[0]["content"]
    assert "revised" in second[0]["content"]


def test_pinned_baseline_does_not_require_git_history(monkeypatch):
    def no_git(*args):
        raise AssertionError("shallow checkout has no baseline history")

    monkeypatch.setattr("eval.profile_policy_fallback.git", no_git)
    baseline = load_baseline()
    store = QdrantPolicyStore.__new__(QdrantPolicyStore)
    assert baseline(store, "driver") == store._fallback_local_search("driver")


def test_custom_baseline_does_not_silently_fall_back_to_pinned_source(monkeypatch):
    import subprocess

    def unavailable(*args):
        raise subprocess.CalledProcessError(128, ["git", *args])

    monkeypatch.setattr("eval.profile_policy_fallback.git", unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        load_baseline("missing-custom-baseline")


def test_pinned_method_preserves_original_ast():
    import inspect

    from eval.baselines.policy_fallback_dede4b0 import SOURCE_METHOD_AST_SHA256
    from eval.profile_policy_fallback import baseline_ast_sha256

    assert baseline_ast_sha256(inspect.getsource(load_baseline())) == SOURCE_METHOD_AST_SHA256
