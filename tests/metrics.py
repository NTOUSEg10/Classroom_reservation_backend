import json
import math
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def latency_summary(seconds, statuses=()):
    values = sorted(value * 1000 for value in seconds)

    def percentile(q):
        return round(values[max(0, math.ceil(len(values) * q) - 1)], 3)

    return {
        "count": len(values),
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
        "max_ms": round(max(values), 3),
        "statuses": dict(Counter(map(str, statuses))),
    }


def write_report(name: str, measurements: dict):
    output = ROOT / "reports" / f"{name}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "environment": {
                    "platform": platform.platform(),
                    "python": sys.version.split()[0],
                    "transport": "localhost PostgreSQL; mock upstream Auth",
                },
                **measurements,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output
