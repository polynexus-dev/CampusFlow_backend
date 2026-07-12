"""
Standalone latency benchmark for the actual production face-recognition
pipeline (campusflow_app/face_utils.py) — run directly against the real
InsightFace model weights, without Docker/Postgres/the full Django app.
Uses django.conf.settings.configure() instead of django.setup() against
the real settings module, since face_utils.py only *reads* settings values
and never touches the app registry or DB.

Usage:
    python bench_face_pipeline.py

Requires (in whatever environment you run this — a venv is fine):
    pip install Django Pillow numpy opencv-python-headless onnxruntime insightface

Re-run this on real production/staging hardware (not a dev laptop) before
trusting the numbers for capacity planning — CPU model, clock speed, and
background load all matter a lot for InsightFace inference time.
"""

import os
import statistics
import sys
import time

import django
from django.conf import settings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.path.join(BASE_DIR, "models", "insightface")
TEST_IMAGES_DIR = os.environ.get(
    "BENCH_IMAGES_DIR",
    r"D:\Polynexus\Servers\Campusnexus\New folder\campusflow_mobile_new\test_images",
)
N_RUNS = int(os.environ.get("BENCH_RUNS", 15))

settings.configure(
    USE_TZ=True,
    INSIGHTFACE_MODEL_NAME="buffalo_l",
    INSIGHTFACE_MODEL_ROOT=MODEL_ROOT,
    FACE_SIMILARITY_THRESHOLD=0.55,
    LIVENESS_BLINK_THRESHOLD=5.5,
)
django.setup()

sys.path.insert(0, BASE_DIR)
from campusflow_app.face_utils import (  # noqa: E402
    _analyse_image,
    _decode_image,
    basic_liveness_check,
    check_frame_motion,
    extract_embedding,
)


def load(name):
    with open(os.path.join(TEST_IMAGES_DIR, name), "rb") as f:
        return f.read()


def bench(label, fn, warmup=2, runs=N_RUNS):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    mean = statistics.mean(times)
    p95 = sorted(times)[int(len(times) * 0.95) - 1]
    print(f"{label:28s} mean={mean:7.1f}ms  p95={p95:7.1f}ms  min={min(times):7.1f}ms  max={max(times):7.1f}ms  (n={runs})")
    return mean


if __name__ == "__main__":
    print(f"Model root: {MODEL_ROOT}")
    print(f"Test images: {TEST_IMAGES_DIR}")
    front = load("front.png")
    left = load("left.png")

    print(f"\nRunning {N_RUNS} iterations per operation (after 2 warmup calls each)...\n")

    print("-- BEFORE: each call independently re-detects the same 'action' frame --")
    liveness_ms = bench("basic_liveness_check", lambda: basic_liveness_check(front))
    motion_ms = bench("check_frame_motion", lambda: check_frame_motion(front, left))
    embed_ms = bench("extract_embedding", lambda: extract_embedding(front))
    pipeline_ms = liveness_ms + motion_ms + embed_ms
    print(f"{'(sum, independent calls)':28s} {pipeline_ms:7.1f}ms")

    def _shared_pipeline():
        cv_image = _decode_image(front)
        face, _ = _analyse_image(cv_image=cv_image)
        basic_liveness_check(front, _face=face, _cv_image=cv_image)
        check_frame_motion(left, front, _face2=face, _img2=cv_image)
        extract_embedding(_face=face)

    print("\n-- AFTER: one shared detection pass (as run_face_pipeline now does) --")
    shared_ms = bench("shared_pipeline (1 detect)", _shared_pipeline)

    print(f"\nFull per-attempt CPU pipeline — before: {pipeline_ms:.1f}ms, after: {shared_ms:.1f}ms "
          f"({pipeline_ms / shared_ms:.2f}x faster)")
    print(f"Single-core sequential throughput (after): {1000 / shared_ms:.2f} attempts/sec/core")
