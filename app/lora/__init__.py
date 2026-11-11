"""LoRA intent adapter — reel skill #5. TOY SCALE (numpy-only, rank-2).

Real PEFT path is documented in adapter.py (not run — needs PyTorch + GPU).
"""
from .adapter import INTENTS, TRAIN_EXAMPLES, ToyLoRA

__all__ = ["INTENTS", "TRAIN_EXAMPLES", "ToyLoRA"]
