"""Self-test for the BuildBuy Copilot AI modules.

Runs the full local flow end to end (retrieval, takeoff, twin, cost+quality
ranking, cache, evals, LoRA, guardrails) and prints MEASURED results.
No network, no paid API, no email sent. All data synthetic.

Run:  python3 tests/self_test.py
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.cache.semantic_cache import SemanticCache  # noqa: E402
from app.evals.eval_gen import build_and_export  # noqa: E402
from app.guardrails.guardrails import Guardrails  # noqa: E402
from app.lora.adapter import ToyLoRA  # noqa: E402
from app.rag.retrieval import HybridRetrieval, load_plan_corpus  # noqa: E402
from app.suppliers.directory import load_suppliers, quality_score  # noqa: E402
from app.suppliers.search import search_suppliers  # noqa: E402
from app.takeoff.engine import compute_takeoff  # noqa: E402
from app.twin.simulator import DigitalTwin  # noqa: E402

DATA = ROOT / "data"
BUYER = (37.5485, -121.9886)  # Fremont, CA


def main() -> None:
    suppliers = load_suppliers(DATA)
    plans = [json.loads(p.read_text()) for p in sorted((DATA / "plans").glob("plan-*.json"))]

    print("== 1. Hybrid RAG ==")
    ret = HybridRetrieval(load_plan_corpus(DATA))
    print(f"backend: {ret.backend}")
    for q in ("What concrete grade is specified for Maple Court ADU?",
              "How many fixtures are in Maple Court ADU?",
              "What is the tensile strength of the moon base?"):
        ans = ret.answer(q)
        print(f"Q: {q}\n   -> {ans['status']}: {ans['answer'][:110]}")
        print(f"      citations: {ans['citations']}")

    print("\n== 2. Takeoff (plan-001) ==")
    for line in compute_takeoff(plans[0]).lines:
        print(f"   {line.material:10s} {line.quantity} {line.unit:5s} "
              f"conf={line.confidence} flagged={line.flagged} [{line.estimate_label}]")

    print("\n== 3. Cost + QUALITY ranking (concrete, 10 m3, Fremont) ==")
    out = search_suppliers(suppliers, "concrete", 10, *BUYER)
    for r in out["ranked"]:
        print(f"   #{r['rank']} {r['name']:32s} landed=${r['landed_cost']:<8} "
              f"cost={r['cost_score']:.2f} quality={r['quality_score']:.2f} "
              f"lead={r['lead_score']:.2f} best_value={r['best_value']:.3f}")
        print(f"        why: {r['why_rank']}")
        print(f"        trade-off: {r['tradeoff']}")
    print(f"   cheapest: {out['cheapest']['name']} (${out['cheapest']['landed_cost']})")
    print(f"   highest quality: {out['highest_quality']['name']} "
          f"({out['highest_quality']['quality_score']})")

    print("\n== 4. Digital twin (top 3: cost + quality risk) ==")
    twin = DigitalTwin(*BUYER, order_date=date(2026, 11, 10))
    for r in out["ranked"][:3]:
        sup = next(s for s in suppliers if s["id"] == r["supplier_id"])
        sim = twin.simulate(sup, "concrete", 10, max_price=1600.0,
                            deadline=date(2026, 11, 20))
        print(f"   {sim.supplier_name}: landed=${sim.landed_cost} delivery={sim.delivery_date} "
              f"cost_risk={sim.cost_risk} quality_risk={sim.quality_risk} "
              f"risk={sim.risk_score} breaks={sim.breaks or 'none'}")
    w = twin.what_if(next(s for s in suppliers if s["id"] == "sup07"),
                     "concrete", 10, price_pct=10, delay_days=3, qty_pct=20,
                     max_price=1600.0, deadline=date(2026, 11, 20))
    print(f"   what-if sup07 (+10% price, +3 days, +20% qty): "
          f"landed ${w['result']['landed_cost']} (delta ${w['delta_landed_usd']}), "
          f"risk delta {w['delta_risk']}, breaks={w['breaks'] or 'none'}")

    print("\n== 5. Semantic cache ==")
    cache = SemanticCache()
    cache.put("plan-001", "What concrete grade is specified?", "grade C25/30")
    print("   paraphrase hit:", cache.get("plan-001", "What is the concrete grade specified?") is not None)
    print("   synonym hit:", cache.get("plan-001", "What cement grade is specified?") is not None)
    print("   unrelated miss:", cache.get("plan-001", "How many bricks are needed?") is None)
    print("   cross-plan miss:", cache.get("plan-002", "What concrete grade is specified?") is None)
    print(f"   stats: {cache.stats()}")

    print("\n== 6. Evals (generated set) ==")
    built = build_and_export(DATA, DATA / "evals")
    print(f"   pairs: {built['pairs']}, quality check pass: {built['quality_check']['pass']}")
    print(f"   files: {built['paths']['jsonl'].name}, {built['paths']['csv'].name}")
    print(f"   metrics: {built['metrics']}")

    print("\n== 7. LoRA toy adapter ==")
    lora = ToyLoRA()
    print(f"   train: {lora.train()}")
    for text in ("Find steel suppliers near Fremont",
                 "How much concrete do I need?",
                 "What does clause 3.2 say?",
                 "Approve the best offer and confirm the order"):
        intent, probs = lora.predict(text)
        print(f"   {text!r:55s} -> {intent} {probs}")
    lora.save(DATA / "lora_toy_adapter.npz")
    print("   saved: data/lora_toy_adapter.npz")

    print("\n== 8. Guardrails ==")
    g = Guardrails()
    cases = [
        ("clean quote request", "Please send a quote for 10 m3 of concrete by Friday.", {}),
        ("price over cap", "Quote is $500", {"max_price": 400.0, "price": 500.0}),
        ("past deadline", "Confirm order", {"deadline": date(2026, 11, 1), "on_date": date(2026, 11, 10)}),
        ("never-pay", "Please send payment now by wire transfer", {}),
        ("PII, sharing OFF", "Contact me at buyer@example.com or 415-555-0132", {"share_contact": False}),
        ("PII, sharing ON", "Contact me at buyer@example.com", {"share_contact": True}),
    ]
    blocked = 0
    for name, text, kw in cases:
        r = g.check(text, **kw)
        if r.action == "block":
            blocked += 1
        print(f"   {name:20s} -> {r.action:6s} passed={r.passed} reason={r.reason}")
    print(f"   blocked: {blocked}/{len(cases)}")

    print("\n== 9. Quality scores (all 12 suppliers) ==")
    for sup in suppliers:
        q, _ = quality_score(sup)
        print(f"   {sup['id']} {sup['name']:32s} quality={q:.3f} "
              f"lead={sup['lead_time_days']}d reply={sup['reply_reliability']} "
              f"defect={sup['defect_rate_pct']}% certs={len(sup['certifications'] or [])}")


if __name__ == "__main__":
    main()
