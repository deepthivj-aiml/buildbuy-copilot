"""LoRA intent adapter — reel skill #5.

TOY SCALE — labelled honestly. A numpy-only rank-2 LoRA adapter for
intent classification of buyer requirements into four intents:
plan_qa, takeoff, supplier_search, buyer.

How it works: a hashed bag-of-words vector (dim 64) feeds a frozen random
base matrix W0 (seed 42, never trained); the LoRA update is
delta_W = (alpha / r) * A @ B with r=2, A (64x2) and B (2x4). Only A and B
are trained, by plain gradient descent on 12 synthetic examples, and saved
as .npz. No GPU, no PyTorch needed for the toy.

REAL PEFT PATH (documented, not run here): replace the hashed features with
a sentence-transformers embedding, load a small base model (e.g.
distilbert-base-uncased) with Hugging Face transformers, wrap it with
peft.LoraConfig(r=8, lora_alpha=16, target_modules=["query", "value"]),
train with peft + Trainer on the buyer's own past requirements (per-user,
never shared data), and save with model.save_pretrained(). That path needs
PyTorch + PEFT + a GPU or patience — the toy above proves the maths and the
save/load contract at zero cost.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

INTENTS = ["plan_qa", "takeoff", "supplier_search", "buyer"]
DIM = 64
RANK = 2
ALPHA = 4.0  # scaling alpha/r = 2.0

# 12 synthetic training examples (buyer phrasing -> intent). Synthetic only.
TRAIN_EXAMPLES = [
    ("What concrete grade is specified on sheet A-101?", "plan_qa"),
    ("How many fixtures are on this plan?", "plan_qa"),
    ("What does clause 3.2 say about the slab?", "plan_qa"),
    ("How much concrete do I need for this slab?", "takeoff"),
    ("Estimate the bricks and steel for this plan", "takeoff"),
    ("What quantities of timber are needed?", "takeoff"),
    ("Find steel suppliers near Fremont", "supplier_search"),
    ("Who supplies bricks in Hayward with a short lead time?", "supplier_search"),
    ("Cheapest concrete supplier within 30 km", "supplier_search"),
    ("Email the top 3 suppliers for a quote", "buyer"),
    ("Negotiate with the supplier within my $400 cap", "buyer"),
    ("Approve the best offer and confirm the order", "buyer"),
]

_KEYWORDS = {
    "plan_qa": {"grade", "clause", "sheet", "specified", "fixtures", "plan", "say"},
    "takeoff": {"much", "estimate", "quantities", "need", "needed", "concrete", "bricks", "steel", "timber"},
    "supplier_search": {"find", "supplies", "supplier", "suppliers", "near", "cheapest", "lead"},
    "buyer": {"email", "negotiate", "approve", "confirm", "order", "quote", "cap"},
}


def _features(text: str) -> "object":
    """Deterministic hashed bag-of-words vector (dim 64), L2-normalised."""
    import numpy as np

    vec = np.zeros(DIM, dtype=np.float64)
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM
        vec[idx] += 1.0
    n = np.linalg.norm(vec)
    return vec / n if n else vec


def _softmax(x):
    import numpy as np

    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


class ToyLoRA:
    """Rank-2 LoRA adapter over a frozen random base (numpy only)."""

    def __init__(self, seed: int = 42):
        import numpy as np

        rng = np.random.default_rng(seed)
        self.W0 = rng.normal(0, 0.1, size=(DIM, len(INTENTS)))
        self.A = rng.normal(0, 0.01, size=(DIM, RANK))
        # B starts small-random, not zero: with B=0 the gradient to A is
        # exactly zero and a toy this small stalls. (Real PEFT inits B=0 and
        # relies on a large A gradient; the toy cannot afford that.)
        self.B = rng.normal(0, 0.01, size=(RANK, len(INTENTS)))
        self.trained = False

    def _logits(self, x):
        import numpy as np

        delta = (ALPHA / RANK) * (self.A @ self.B)
        return x @ (self.W0 + delta)

    def predict_proba(self, text: str) -> dict[str, float]:
        import numpy as np

        x = _features(text)
        probs = _softmax(self._logits(x))
        return {intent: round(float(p), 3) for intent, p in zip(INTENTS, probs)}

    def predict(self, text: str) -> tuple[str, dict[str, float]]:
        probs = self.predict_proba(text)
        return max(probs, key=probs.get), probs

    def predict_keyword_fallback(self, text: str) -> str:
        """Rule fallback when numpy is unavailable — keywords only."""
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        best, best_n = INTENTS[0], -1
        for intent, words in _KEYWORDS.items():
            n = len(tokens & words)
            if n > best_n:
                best, best_n = intent, n
        return best

    def train(self, examples=None, epochs: int = 500, lr: float = 1.0) -> dict:
        """Train ONLY A and B (W0 frozen) with gradient descent."""
        import numpy as np

        examples = examples or TRAIN_EXAMPLES
        X = np.stack([_features(t) for t, _ in examples])
        Y = np.zeros((len(examples), len(INTENTS)))
        for i, (_, intent) in enumerate(examples):
            Y[i, INTENTS.index(intent)] = 1.0
        scale = ALPHA / RANK
        for _ in range(epochs):
            logits = self._logits(X)
            probs = _softmax(logits)
            grad_logits = (probs - Y) / len(examples)
            grad_W = X.T @ grad_logits
            # dL/dB = scale * A^T grad_W ; dL/dA = scale * grad_W B^T
            grad_B = scale * (self.A.T @ grad_W)
            grad_A = scale * (grad_W @ self.B.T)
            self.B -= lr * grad_B
            self.A -= lr * grad_A
        self.trained = True
        preds = [_softmax(self._logits(x)).argmax() for x in X]
        acc = float(np.mean([p == INTENTS.index(y) for p, (_, y) in zip(preds, examples)]))
        return {"epochs": epochs, "train_accuracy": round(acc, 3), "n_examples": len(examples)}

    def save(self, path: str | Path) -> Path:
        import numpy as np

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, W0=self.W0, A=self.A, B=self.B,
                 intents=np.array(INTENTS), rank=np.array(RANK))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "ToyLoRA":
        import numpy as np

        data = np.load(path, allow_pickle=False)
        obj = cls.__new__(cls)
        obj.W0, obj.A, obj.B = data["W0"], data["A"], data["B"]
        obj.trained = True
        return obj
