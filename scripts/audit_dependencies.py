"""Query OSV for locked public Python package versions without extra dependencies."""

import json
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parent.parent
packages = []
for line in (
    (root / "requirements.lock").read_text(encoding="utf-8").splitlines()
):
    if "==" in line and not line.startswith("#"):
        name, version = line.split("==", 1)
        packages.append({"name": name, "version": version})
payload = {
    "queries": [
        {
            "package": {"name": item["name"], "ecosystem": "PyPI"},
            "version": item["version"],
        }
        for item in packages
    ]
}
request = urllib.request.Request(
    "https://api.osv.dev/v1/querybatch",
    json.dumps(payload).encode(),
    {"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    results = json.load(response)["results"]
assert len(results) == len(packages), (
    "Advisory service returned incomplete results"
)
findings = [
    {**item, "advisories": [vuln["id"] for vuln in result.get("vulns", [])]}
    for item, result in zip(packages, results)
    if result.get("vulns")
]
(root / "reports").mkdir(exist_ok=True)
(root / "reports/python-dependencies.json").write_text(
    json.dumps(
        {
            "source": "https://api.osv.dev/v1/querybatch",
            "checked_packages": len(packages),
            "findings": findings,
        },
        indent=2,
    ),
    encoding="utf-8",
)
print(
    json.dumps(
        {"checked_packages": len(packages), "findings": findings}, indent=2
    )
)
if findings:
    raise SystemExit(1)
