"""Module-boundary tests — each module rebuildable / replaceable alone.

Checks, by reading the source (no import side effects beyond the
interface checks):
1. Every module package has an __init__.py that exports its public
   interface (__all__).
2. Each module's public interface actually imports (names exist).
3. Cross-module imports stay inside the allowed dependency map —
   modules talk through app/schemas.py, app/config.py, app/db, or the
   documented edges only. app/integrations.py is the ONE wiring module
   allowed to import every AI module; the API layer may import it.
4. No auto-location code anywhere (no geolocation API, no IP lookup),
   and no hard dependency on torch / faiss (both optional).

Run alone:  .venv/bin/python -m pytest tests/test_modularity.py -v
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP = ROOT / "app"

# module -> public names its __init__ must export
INTERFACES = {
    "app.rag": ["HybridRetrieval", "load_plan_corpus", "build_plan_corpus"],
    "app.vlm": ["VisionReader", "describe_plan", "detect_scale", "answer_about_plan"],
    "app.takeoff": ["compute_takeoff", "verify_reconciliation", "TakeoffResult"],
    "app.suppliers": ["search_suppliers", "geocode_location", "best_value_score",
                      "landed_cost_breakdown", "load_suppliers", "quality_score"],
    "app.twin": ["DigitalTwin", "Simulation", "shipping_cost_usd"],
    "app.ranking": ["rank_shortlist", "simulate_cost_and_quality"],
    "app.agents": ["BuyerGraph", "finder_node", "approval_gate_node"],
    "app.email": ["EmailService", "drain_outbox", "idempotency_key"],
    "app.guardrails": ["Guardrails", "GuardrailResult"],
    "app.cache": ["SemanticCache", "normalize"],
    "app.evals": ["generate_eval_pairs", "run_eval", "quality_check"],
    "app.lora": ["ToyLoRA", "INTENTS"],
    "app.observability": ["compute_daily_metrics"],
    "app.records": ["build_records", "build_export", "to_csv", "to_json"],
    "app.mcp": ["create_server", "TOOL_NAMES", "call_tool", "list_tools",
                "SessionStore"],
    "app.integrations": ["MODULE_AVAILABILITY", "rag_retrieve", "run_takeoff",
                         "twin_simulate", "guardrail_check", "classify_intent"],
}

# module (file stem dir) -> app.* imports it is allowed to make.
# Everything else must go through app/schemas.py, app/config.py or
# app/db — or the wiring module app/integrations.py.
ALLOWED_IMPORTS = {
    "rag": set(),
    "vlm": set(),
    "takeoff": set(),
    "suppliers": {"app.twin"},  # lazy import of shipping_cost_usd only
    "twin": {"app.suppliers"},  # lazy import of quality_score only
    "ranking": {"app.suppliers"},  # canonical best-value formula
    "agents": {"app.integrations", "app.ranking", "app.email", "app.db",
               "app.config", "app.schemas"},
    "email": {"app.config", "app.db"},
    "guardrails": set(),
    "cache": set(),
    "evals": {"app.guardrails", "app.rag"},
    "lora": set(),
    "observability": {"app.db"},
    "records": {"app.db"},
    "mcp": {"app.suppliers", "app.takeoff", "app.email", "app.guardrails",
            "app.observability", "app.live"},  # read/draft only — no send, no order
    "integrations": {"app.rag", "app.takeoff", "app.suppliers", "app.twin",
                     "app.guardrails", "app.cache", "app.evals", "app.lora",
                     "app.ranking", "app.config"},
    "api": {"app.integrations", "app.agents", "app.email", "app.records",
            "app.db", "app.config", "app.schemas", "app.observability",
            "app.ranking", "app.live"},  # live: session-only contact flow
    # Root-level single-file modules (app/*.py, not packages).
    "ranking": {"app.suppliers"},
    "live": set(),  # stdlib only — the live flow imports nothing from app.*
    "main": {"app.agents", "app.api", "app.db"},
}
ALWAYS_ALLOWED = {"app.config", "app.schemas", "app.db", "app.logging_setup"}


def _module_of(path: Path) -> str:
    rel = path.relative_to(APP)
    if len(rel.parts) > 1:
        return rel.parts[0]
    return rel.stem  # root-level single-file module: integrations, ranking, ...


def _app_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app."):
                    found.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("app."):
                found.add(node.module)
            elif node.level and node.module:
                # relative import: resolve against the file's package
                pkg = ".".join(path.relative_to(APP).parts[:-1])
                found.add(f"app.{pkg}.{node.module}" if pkg else f"app.{node.module}")
    return found


def test_every_module_exports_its_public_interface():
    import importlib

    for dotted, names in INTERFACES.items():
        mod = importlib.import_module(dotted)
        for name in names:
            assert hasattr(mod, name), f"{dotted} is missing {name}"
        if dotted != "app.ranking" and dotted != "app.observability":
            assert getattr(mod, "__all__", None), f"{dotted} has no __all__"


def test_cross_module_imports_stay_inside_the_map():
    violations = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "__init__.py":
            continue
        mod = _module_of(path)
        if mod not in ALLOWED_IMPORTS:
            continue
        for imp in _app_imports(path):
            top = ".".join(imp.split(".")[:2])
            if top in ALWAYS_ALLOWED or top in ALLOWED_IMPORTS[mod]:
                continue
            if top == f"app.{mod}":
                continue
            violations.append(f"{path.relative_to(ROOT)}: {mod} imports {imp}")
    assert violations == [], "\n".join(violations)


def test_no_auto_location_and_no_hard_heavy_deps():
    banned_location = ("navigator.geolocation", "getCurrentPosition",
                       "ip-api", "ipinfo", "ipify", "geocoder.ip")
    hits = []
    for path in list(APP.rglob("*.py")) + list((ROOT / "frontend").glob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text()
        for needle in banned_location:
            if needle in text:
                hits.append(f"{path.relative_to(ROOT)}: {needle!r}")
    # torch / faiss must never be a HARD import: only inside try/except.
    for path in APP.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        guarded: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for sub in ast.walk(node):
                    guarded.add(id(sub))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                if any(n.split(".")[0] in ("torch", "faiss") for n in names):
                    assert id(node) in guarded, (
                        f"{path.relative_to(ROOT)}: hard import of "
                        f"{names} outside try/except"
                    )
    assert hits == [], "\n".join(hits)
