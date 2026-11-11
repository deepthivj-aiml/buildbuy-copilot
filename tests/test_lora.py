"""Tests for LoRA toy adapter — numpy-only rank-2 intent adapter, train/save/load.

Run alone:  .venv/bin/python -m pytest tests/test_lora.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.lora.adapter import ToyLoRA  # noqa: E402

DATA = ROOT / "data"


def test_lora_toy_adapter():
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("SKIP test_lora_toy_adapter: numpy not installed")
        return
    adapter = ToyLoRA()
    result = adapter.train()
    assert result["train_accuracy"] >= 0.9, result
    intent, _ = adapter.predict("Find steel suppliers near Fremont")
    assert intent == "supplier_search", intent
    intent2, _ = adapter.predict("How much concrete do I need?")
    assert intent2 == "takeoff", intent2
    path = ROOT / "data" / "lora_toy_adapter.npz"
    adapter.save(path)
    loaded = ToyLoRA.load(path)
    assert loaded.predict("Find steel suppliers near Fremont")[0] == "supplier_search"
