"""Generate synthetic floor-plan PNGs from the plan JSON files (PIL only).

Run:  python3 data/plans/generate_pngs.py
If PIL is unavailable the script exits with a clear message and the JSON
metadata alone remains the source of truth — no plan image is claimed.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("PIL not available — skipping PNG generation (JSON metadata only).")
        return 1
    for plan_file in sorted(HERE.glob("plan-*.json")):
        plan = json.loads(plan_file.read_text())
        img = Image.new("RGB", (600, 500), "white")
        d = ImageDraw.Draw(img)
        d.rectangle([10, 10, 590, 490], outline="black", width=2)
        d.text((20, 18), f"{plan['title']}  |  Sheet {plan['sheet']}  |  Scale {plan['scale']}", fill="black")
        for region in plan["regions"]:
            x0, y0, x1, y1 = region["bbox"]
            d.rectangle([x0, y0, x1, y1], outline="blue", width=2)
            d.text((x0 + 6, y0 + 6), region["label"], fill="blue")
            d.text((x0 + 6, y0 + 22), region["region_id"], fill="blue")
        d.text((20, 472), "SYNTHETIC DEMO PLAN — not a real client drawing", fill="red")
        out = HERE / f"{plan['plan_id']}.png"
        img.save(out)
        print(f"wrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
