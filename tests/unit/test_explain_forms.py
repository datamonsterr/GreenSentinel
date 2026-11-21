from src.services.explain_forms import REASONS, build_form, driver_form_view, statement_text, validate_answers


def _required(form):
    return {
        x["id"]: (x["options"][0]["value"] if x["type"] == "choice" else "x") for x in form["fields"] if x["required"]
    }


WF = {
    "code": "WF_X",
    "version": 3,
    "body": {
        "ask_first": ["Điện thoại có lỗi gì không?", {"text": "Có ticket không?", "type": "ticket"}, "Câu 3", "Câu 4"]
    },
}


def test_fixed_form_per_reason_has_typed_required_fields():
    f = build_form("RealTrip", None, k=3)
    types = {x["type"] for x in f["fields"]}
    assert {"text", "time", "location", "amount", "photo"} <= types
    assert all(x["origin"] == "fixed" for x in f["fields"])
    assert any(x["required"] for x in f["fields"]) and any(not x["required"] for x in f["fields"])
    assert f["form_version"].startswith("RealTrip.")
    assert f["workflow"] is None


def test_other_reason_is_free_text_and_photo_only():
    f = build_form("Other", None, k=3)
    assert [x["type"] for x in f["fields"]] == ["text", "photo"]
    assert f["has_question_set"] is False


def test_all_reasons_build():
    for r in REASONS:
        assert build_form(r, None, k=3)["fields"]


def test_dynamic_questions_capped_by_k_optional_and_versioned():
    f = build_form("RealTrip", WF, k=2)
    dyn = [x for x in f["fields"] if x["origin"] == "workflow"]
    assert len(dyn) == 2 and all(not x["required"] for x in dyn)
    assert dyn[1]["type"] == "ticket"
    assert f["workflow"] == {"code": "WF_X", "version": 3}
    assert "WF_X@3" in f["form_version"]
    assert build_form("RealTrip", WF, k=0)["workflow"]["code"] == "WF_X"
    assert not [x for x in build_form("RealTrip", WF, k=0)["fields"] if x["origin"] == "workflow"]


def test_driver_view_hides_origin_and_workflow():
    v = driver_form_view(build_form("RealTrip", WF, k=1))
    assert "workflow" not in v and all("origin" not in x for x in v["fields"])


def test_validate_missing_required_and_types():
    f = build_form("RealTrip", WF, k=1)
    r = validate_answers(f, {})
    assert "pickup_place" in r["missing"]
    ans = _required(f)
    ans["payment_amount"] = "abc"
    r = validate_answers(f, ans)
    assert r["missing"] == [] and {"field": "payment_amount", "code": "invalid_amount"} in r["invalid"]
    ans["payment_amount"] = "85.000"
    assert validate_answers(f, ans) == {"missing": [], "invalid": []}


def test_validate_choice_and_ticket():
    f = build_form("NotDone", None, k=0)
    choice = next(x for x in f["fields"] if x["type"] == "choice")
    r = validate_answers(
        f, {choice["id"]: "zzz", **{x["id"]: "ok" for x in f["fields"] if x["required"] and x["type"] != "choice"}}
    )
    assert {"field": choice["id"], "code": "invalid_choice"} in r["invalid"]
    t = build_form("RealTrip", WF, k=2)
    tid = next(x["id"] for x in t["fields"] if x["type"] == "ticket")
    base = _required(t)
    base["payment_amount"] = 85000
    assert {"field": tid, "code": "invalid_ticket"} in validate_answers(t, {**base, tid: "!!"})["invalid"]
    assert validate_answers(t, {**base, tid: "0000-1234"})["invalid"] == []


def test_statement_text_orders_by_form_and_skips_empty():
    f = build_form("Other", None, k=0)
    txt = statement_text(f, {f["fields"][0]["id"]: "Tôi muốn gặp VH"})
    assert "Tôi muốn gặp VH" in txt
