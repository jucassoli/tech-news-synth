"""D-07 — numpy float32 centroid bytes roundtrip (no DB)."""

from __future__ import annotations

import numpy as np


def test_float32_bytes_roundtrip() -> None:
    original = np.asarray([0.1, 0.2, 0.3, -0.5, 1e-6], dtype=np.float32)
    blob = original.tobytes()
    restored = np.frombuffer(blob, dtype=np.float32)
    np.testing.assert_array_equal(original, restored)
    # Byte-for-byte determinism across calls.
    assert blob == original.tobytes()


def test_float32_byte_length_matches_dim() -> None:
    # 4 bytes per float32.
    assert len(np.zeros(128, dtype=np.float32).tobytes()) == 128 * 4


def test_dtype_drift_detection() -> None:
    # If someone accidentally wrote float64, np.frombuffer(..., float32) on the
    # same blob would produce 2x the elements. Explicit test so drift surfaces.
    arr64 = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)
    blob = arr64.tobytes()
    # 3 float64 = 24 bytes = 6 float32 — proves dtype matters.
    assert len(np.frombuffer(blob, dtype=np.float32)) == 6
