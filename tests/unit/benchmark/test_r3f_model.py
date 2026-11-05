"""Unit tests for R3F trajectory sequence model architecture and checkpoint I/O."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from scripts.benchmark.experiments.r3f.dataset import (  # noqa: E402
    MODEL_CLASSES,
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
    NUM_STEPS,
)
from scripts.benchmark.experiments.r3f.model import (  # noqa: E402
    R3FTrajectoryClassifier,
    load_r3f_model,
    save_r3f_model,
)


def test_model_forward_shape():
    batch_size = 4
    num_classes = len(MODEL_CLASSES)

    model = R3FTrajectoryClassifier(
        in_channels=NUM_CHANNELS,
        static_dim=NUM_STATIC_FEATURES,
        num_classes=num_classes,
    )
    model.eval()

    x_seq = torch.randn(batch_size, NUM_CHANNELS, NUM_STEPS)
    x_static = torch.randn(batch_size, NUM_STATIC_FEATURES)

    with torch.no_grad():
        logits = model(x_seq, x_static)
        probs = model.predict_probabilities(x_seq, x_static)

    assert logits.shape == (batch_size, num_classes)
    assert probs.shape == (batch_size, num_classes)

    # Probabilities must sum to 1.0 along class dimension
    prob_sums = probs.sum(dim=1)
    torch.testing.assert_close(prob_sums, torch.ones(batch_size), atol=1e-5, rtol=1e-5)


def test_model_save_and_load():
    model = R3FTrajectoryClassifier(
        in_channels=NUM_CHANNELS,
        static_dim=NUM_STATIC_FEATURES,
        num_classes=len(MODEL_CLASSES),
    )
    model.eval()

    x_seq = torch.randn(2, NUM_CHANNELS, NUM_STEPS)
    x_static = torch.randn(2, NUM_STATIC_FEATURES)

    with torch.no_grad():
        orig_probs = model.predict_probabilities(x_seq, x_static)

    with tempfile.TemporaryDirectory() as tmp_dir:
        ckpt_path = Path(tmp_dir) / "test_model.pt"
        save_r3f_model(model, ckpt_path, metadata={"epoch": 10, "val_f1": 0.85})

        loaded_model, meta = load_r3f_model(ckpt_path)
        assert meta.get("epoch") == 10

        with torch.no_grad():
            loaded_probs = loaded_model.predict_probabilities(x_seq, x_static)

        torch.testing.assert_close(orig_probs, loaded_probs, atol=1e-6, rtol=1e-6)
