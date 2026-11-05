"""Unit tests for R3D Out-Of-Fold (OOF) prediction generation (Issue #554 / Epic #494)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.benchmark.experiments.r3c.train import GBM_CLASSES
from scripts.benchmark.experiments.r3d.oof import (
    create_grouped_folds,
    save_oof_parquet,
)


def test_create_grouped_folds_no_driver_overlap():
    """Verify that driver_id groups are strictly disjoint across folds."""
    # 20 drivers, 3 trips each
    driver_ids = []
    labels = []
    for d in range(20):
        drv = f"drv_{d:03d}"
        for t in range(3):
            driver_ids.append(drv)
            labels.append(GBM_CLASSES[d % len(GBM_CLASSES)])

    folds = create_grouped_folds(driver_ids, labels, n_splits=5, seed=42)
    assert len(folds) == len(driver_ids)

    for fold_idx in range(5):
        val_drivers = {driver_ids[i] for i, f in enumerate(folds) if f == fold_idx}
        train_drivers = {driver_ids[i] for i, f in enumerate(folds) if f != fold_idx}
        overlap = val_drivers.intersection(train_drivers)
        assert len(overlap) == 0, f"Driver leak in fold {fold_idx}: {overlap}"


def test_oof_parquet_roundtrip():
    """Verify saving and reloading OOF data in parquet format with pyarrow."""
    rng = np.random.RandomState(42)

    data: dict[str, list[Any]] = {
        "trip_ref": [f"trip_{i:03d}" for i in range(20)],
        "driver_id": [f"drv_{i // 2:02d}" for i in range(20)],
        "label": [GBM_CLASSES[i % len(GBM_CLASSES)] for i in range(20)],
        "fold": [i % 5 for i in range(20)],
    }
    for cls_name in GBM_CLASSES:
        data[f"r3c_p_{cls_name}"] = []
        data[f"r3f_p_{cls_name}"] = []

    for i in range(20):
        c_r3c = rng.dirichlet(np.ones(len(GBM_CLASSES)))
        c_r3f = rng.dirichlet(np.ones(len(GBM_CLASSES)))
        for idx, cls_name in enumerate(GBM_CLASSES):
            data[f"r3c_p_{cls_name}"].append(float(c_r3c[idx]))
            data[f"r3f_p_{cls_name}"].append(float(c_r3f[idx]))

    table = pa.Table.from_pydict(data)

    with tempfile.TemporaryDirectory() as tmpdir:
        pq_path = Path(tmpdir) / "oof_test.parquet"
        save_oof_parquet(table, pq_path)

        assert pq_path.exists()
        loaded_table = pq.read_table(pq_path)
        assert loaded_table.num_rows == 20
        assert "trip_ref" in loaded_table.column_names
        assert "driver_id" in loaded_table.column_names
        assert "fold" in loaded_table.column_names
        assert "label" in loaded_table.column_names

        # Verify probability sum invariant
        for cls_name in GBM_CLASSES:
            assert f"r3c_p_{cls_name}" in loaded_table.column_names
            assert f"r3f_p_{cls_name}" in loaded_table.column_names

        loaded_dict = loaded_table.to_pydict()
        r3c_sums = np.zeros(20)
        r3f_sums = np.zeros(20)
        for c in GBM_CLASSES:
            r3c_sums += np.array(loaded_dict[f"r3c_p_{c}"])
            r3f_sums += np.array(loaded_dict[f"r3f_p_{c}"])

        np.testing.assert_allclose(r3c_sums, 1.0, atol=1e-5)
        np.testing.assert_allclose(r3f_sums, 1.0, atol=1e-5)
