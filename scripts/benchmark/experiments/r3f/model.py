"""Deep learning trajectory sequence classifier architecture and checkpoint I/O."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F  # noqa: N812

    _HAS_TORCH = True
    _ModuleBase = nn.Module
except ImportError:
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]
    _HAS_TORCH = False
    _ModuleBase = object  # type: ignore[misc,assignment]

from src.services.fraud_classifier.features_sequence import (
    MODEL_CLASSES,
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
    NUM_STEPS,
)


class ConvResidualBlock(_ModuleBase):
    """1D-CNN residual block with optional channel projection and pooling."""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int = 5,
        stride: int = 1,
        pool: bool = False,
    ):
        if not _HAS_TORCH:
            raise ImportError("torch is required to instantiate ConvResidualBlock")
        super().__init__()
        padding = kernel_size // 2
        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size, padding=padding, stride=stride)
        self.bn1 = nn.BatchNorm1d(out_channels)
        self.act1 = nn.LeakyReLU(0.1, inplace=True)

        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size, padding=padding)
        self.bn2 = nn.BatchNorm1d(out_channels)
        self.act2 = nn.LeakyReLU(0.1, inplace=True)

        if in_channels != out_channels or stride != 1:
            self.shortcut = nn.Sequential(
                nn.Conv1d(in_channels, out_channels, kernel_size=1, stride=stride),
                nn.BatchNorm1d(out_channels),
            )
        else:
            self.shortcut = nn.Identity()

        self.pool = nn.MaxPool1d(2) if pool else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        res = self.shortcut(x)
        out = self.act1(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        out = self.act2(out + res)
        out = self.pool(out)
        return out


class R3FTrajectoryClassifier(_ModuleBase):
    """1D-CNN trajectory sequence classifier combining resampled kinematics and static trip context."""

    def __init__(
        self,
        in_channels: int = NUM_CHANNELS,
        static_dim: int = NUM_STATIC_FEATURES,
        num_classes: int = len(MODEL_CLASSES),
        num_steps: int = NUM_STEPS,
    ):
        if not _HAS_TORCH:
            raise ImportError("torch is required to instantiate R3FTrajectoryClassifier")
        super().__init__()
        self.in_channels = in_channels
        self.static_dim = static_dim
        self.num_classes = num_classes
        self.num_steps = num_steps

        # 1. Sequence Feature Extractor
        self.in_conv = nn.Sequential(
            nn.Conv1d(in_channels, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.LeakyReLU(0.1, inplace=True),
        )

        self.block1 = ConvResidualBlock(64, 64, kernel_size=5, pool=True)  # -> (B, 64, 64)
        self.block2 = ConvResidualBlock(64, 128, kernel_size=5, pool=True)  # -> (B, 128, 32)
        self.block3 = ConvResidualBlock(128, 128, kernel_size=3, pool=False)  # -> (B, 128, 32)

        self.avg_pool = nn.AdaptiveAvgPool1d(1)
        self.max_pool = nn.AdaptiveMaxPool1d(1)
        seq_feat_dim = 128 * 3  # 384 (avg + max + min)

        # 2. Static Feature MLP
        self.static_mlp = nn.Sequential(
            nn.Linear(static_dim, 32),
            nn.LeakyReLU(0.1, inplace=True),
            nn.Linear(32, 32),
            nn.LeakyReLU(0.1, inplace=True),
        )

        # 3. Fusion and Classification Head
        total_dim = seq_feat_dim + 32  # 416
        self.head = nn.Sequential(
            nn.Linear(total_dim, 96),
            nn.BatchNorm1d(96),
            nn.LeakyReLU(0.1, inplace=True),
            nn.Dropout(0.25),
            nn.Linear(96, num_classes),
        )

    def forward(self, x_seq: torch.Tensor, x_static: torch.Tensor) -> torch.Tensor:
        """Forward pass returning unnormalized class logits (B, num_classes)."""
        h = self.in_conv(x_seq)
        h = self.block1(h)
        h = self.block2(h)
        h = self.block3(h)

        avg_f = self.avg_pool(h).flatten(1)
        max_f = self.max_pool(h).flatten(1)
        min_f = (-self.max_pool(-h)).flatten(1)
        seq_feat = torch.cat([avg_f, max_f, min_f], dim=1)

        static_feat = self.static_mlp(x_static)

        fused = torch.cat([seq_feat, static_feat], dim=1)
        logits = self.head(fused)
        return logits

    def predict_probabilities(self, x_seq: torch.Tensor, x_static: torch.Tensor) -> torch.Tensor:
        """Return normalized class probabilities via softmax (B, num_classes)."""
        logits = self.forward(x_seq, x_static)
        return F.softmax(logits, dim=-1)


def save_r3f_model(
    model: R3FTrajectoryClassifier,
    path: Path | str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Save model state dict and architecture metadata to checkpoint."""
    import torch

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state_dict": model.state_dict(),
        "in_channels": model.in_channels,
        "static_dim": model.static_dim,
        "num_classes": model.num_classes,
        "num_steps": model.num_steps,
        "metadata": metadata or {},
    }
    torch.save(payload, p)


def load_r3f_model(
    path: Path | str,
    device: str = "cpu",
) -> tuple[R3FTrajectoryClassifier, dict[str, Any]]:
    """Load model checkpoint and instantiate trained R3FTrajectoryClassifier."""
    import torch

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"R3F model checkpoint not found at {p}")

    checkpoint = torch.load(p, map_location=device)
    model = R3FTrajectoryClassifier(
        in_channels=checkpoint.get("in_channels", NUM_CHANNELS),
        static_dim=checkpoint.get("static_dim", NUM_STATIC_FEATURES),
        num_classes=checkpoint.get("num_classes", len(MODEL_CLASSES)),
        num_steps=checkpoint.get("num_steps", NUM_STEPS),
    )
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device)
    model.eval()
    return model, checkpoint.get("metadata", {})
