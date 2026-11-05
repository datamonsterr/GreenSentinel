"""Text leakage classifier: fits TF-IDF + Logistic Regression on train split and reports validation macro-F1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score


def extract_trip_text(trip: dict[str, Any]) -> str:
    parts: list[str] = []
    for turn in trip.get("conversation") or []:
        txt = turn.get("text")
        if txt:
            parts.append(str(txt))
    rep = trip.get("customer_report")
    if rep:
        parts.append(str(rep))
    obj = trip.get("driver_objection")
    if isinstance(obj, dict):
        obj_txt = obj.get("text")
        if obj_txt:
            parts.append(str(obj_txt))
    elif isinstance(obj, str) and obj:
        parts.append(obj)
    return " ".join(parts).strip()


def evaluate_text_leakage_classifier(
    trips_input: Path | list[dict[str, Any]],
    train_split: str = "train",
    val_split: str = "validation",
    target_macro_f1: float = 0.45,
) -> dict[str, Any]:
    trips: list[dict[str, Any]] = []
    if isinstance(trips_input, (str, Path)):
        with open(trips_input, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    trips.append(json.loads(line))
    else:
        trips = trips_input

    train_texts: list[str] = []
    train_labels: list[str] = []
    val_texts: list[str] = []
    val_labels: list[str] = []

    for t in trips:
        split = t.get("split")
        lbl = t.get("label")
        if not lbl:
            continue
        txt = extract_trip_text(t)
        if split == train_split:
            train_texts.append(txt)
            train_labels.append(lbl)
        elif split == val_split:
            val_texts.append(txt)
            val_labels.append(lbl)

    if not train_texts or not val_texts:
        # Fallback split if dataset didn't have validation or train labeled splits
        n_half = len(trips) // 2
        for idx, t in enumerate(trips):
            txt = extract_trip_text(t)
            lbl = t.get("label", "unknown")
            if idx < n_half:
                train_texts.append(txt)
                train_labels.append(lbl)
            else:
                val_texts.append(txt)
                val_labels.append(lbl)

    vectorizer = TfidfVectorizer(max_features=2500, ngram_range=(1, 2), min_df=1)
    x_train = vectorizer.fit_transform(train_texts)
    x_val = vectorizer.transform(val_texts)

    clf = LogisticRegression(class_weight="balanced", max_iter=300, random_state=42)
    clf.fit(x_train, train_labels)

    val_preds = clf.predict(x_val)
    macro_f1 = float(f1_score(val_labels, val_preds, average="macro", zero_division=0))
    report = classification_report(val_labels, val_preds, output_dict=True, zero_division=0)

    per_class_f1 = {
        cls: round(float(metrics["f1-score"]), 4)
        for cls, metrics in report.items()
        if isinstance(metrics, dict) and "f1-score" in metrics
    }

    return {
        "macro_f1": round(macro_f1, 4),
        "target_macro_f1": target_macro_f1,
        "is_below_target": macro_f1 <= target_macro_f1,
        "train_samples": len(train_texts),
        "val_samples": len(val_texts),
        "per_class_f1": per_class_f1,
    }
