#!/usr/bin/env python3
"""Probe Xianyu rental ROI projects without modifying files."""

from __future__ import annotations

import argparse
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        return {"_error": f"invalid json: {exc}"}


def has_text(root: Path, patterns: list[str], needle: str) -> bool:
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                try:
                    if needle in path.read_text(encoding="utf-8", errors="ignore"):
                        return True
                except OSError:
                    continue
    return False


def socket_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_json(url: str, method: str = "GET", timeout: float = 8) -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(body)
            except json.JSONDecodeError:
                parsed = body[:500]
            return {
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "body": parsed,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": exc.code, "body": body[:500]}
    except Exception as exc:  # noqa: BLE001 - probe should report all failures
        return {"ok": False, "error": str(exc)}


def inspect_repo(root: Path) -> dict[str, Any]:
    root_pkg = load_json(root / "package.json")
    backend_pkg = load_json(root / "backend" / "package.json")
    backend_deps = {}
    if backend_pkg:
        backend_deps.update(backend_pkg.get("dependencies", {}))
        backend_deps.update(backend_pkg.get("devDependencies", {}))

    node_markers = {
        ".nvmrc": (root / ".nvmrc").read_text(encoding="utf-8", errors="ignore").strip()
        if (root / ".nvmrc").exists()
        else None,
        ".node-version": (root / ".node-version").read_text(encoding="utf-8", errors="ignore").strip()
        if (root / ".node-version").exists()
        else None,
        "root_engines": (root_pkg or {}).get("engines") if root_pkg else None,
        "backend_engines": (backend_pkg or {}).get("engines") if backend_pkg else None,
    }

    return {
        "root": str(root),
        "exists": root.exists(),
        "is_git_repo": (root / ".git").exists(),
        "has_root_package": root_pkg is not None,
        "has_backend_package": backend_pkg is not None,
        "root_scripts": sorted((root_pkg or {}).get("scripts", {}).keys()) if root_pkg else [],
        "backend_scripts": sorted((backend_pkg or {}).get("scripts", {}).keys()) if backend_pkg else [],
        "uses_vite": any((root / name).exists() for name in ["vite.config.ts", "vite.config.js", "vite.config.mjs"]),
        "uses_better_sqlite3": "better-sqlite3" in backend_deps,
        "node_markers": node_markers,
        "has_refresh_route": has_text(root, ["backend/src/**/*.ts", "src/**/*.ts", "src/**/*.tsx"], "/refresh"),
        "has_investment_calculator": has_text(root, ["backend/src/**/*.ts", "src/**/*.ts", "src/**/*.tsx"], "investmentCalculator"),
        "has_recharts": has_text(root, ["src/**/*.ts", "src/**/*.tsx", "package.json"], "recharts"),
    }


def summarize_refresh_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"body_type": type(body).__name__}

    products = body.get("products")
    data = body.get("data")
    if products is None and isinstance(data, dict):
        products = data.get("products")

    meta = body.get("meta")
    if meta is None and isinstance(data, dict):
        meta = data.get("meta")

    return {
        "success": body.get("success"),
        "product_count": len(products) if isinstance(products, list) else None,
        "message": meta.get("message") if isinstance(meta, dict) else body.get("message"),
        "recent_runs": len(meta.get("recentRuns", [])) if isinstance(meta, dict) else None,
    }


def probe_http(backend_url: str | None, frontend_url: str | None, post_refresh: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}

    if frontend_url:
        host = urllib.request.urlparse(frontend_url).hostname or "127.0.0.1"
        port = urllib.request.urlparse(frontend_url).port or 80
        result["frontend_port_open"] = socket_open(host, port)
        frontend = http_json(frontend_url)
        result["frontend_reachable"] = frontend["ok"] or frontend.get("status") == 200
        result["frontend_status"] = frontend.get("status")

    if backend_url:
        parsed = urllib.request.urlparse(backend_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        result["backend_port_open"] = socket_open(host, port)
        result["health"] = http_json(backend_url.rstrip("/") + "/api/health")
        result["products"] = http_json(backend_url.rstrip("/") + "/api/products")
        result["refresh_status"] = http_json(backend_url.rstrip("/") + "/api/products/refresh/status")
        if post_refresh:
            refresh = http_json(backend_url.rstrip("/") + "/api/products/refresh", method="POST", timeout=20)
            result["refresh_post"] = refresh
            result["refresh_summary"] = summarize_refresh_body(refresh.get("body"))

    return result


def render_markdown(report: dict[str, Any]) -> str:
    repo = report["repo"]
    lines = [
        "# Xianyu ROI QA Probe",
        "",
        f"- Root: `{repo['root']}`",
        f"- Git repo: `{repo['is_git_repo']}`",
        f"- Root package: `{repo['has_root_package']}`",
        f"- Backend package: `{repo['has_backend_package']}`",
        f"- Vite: `{repo['uses_vite']}`",
        f"- better-sqlite3: `{repo['uses_better_sqlite3']}`",
        f"- Refresh route hint: `{repo['has_refresh_route']}`",
        f"- Investment calculator hint: `{repo['has_investment_calculator']}`",
        f"- Recharts hint: `{repo['has_recharts']}`",
        "",
        "## Node Markers",
    ]
    for key, value in repo["node_markers"].items():
        lines.append(f"- {key}: `{value}`")

    http = report.get("http") or {}
    if http:
        lines.extend(["", "## HTTP"])
        for key in ["frontend_port_open", "frontend_reachable", "frontend_status", "backend_port_open"]:
            if key in http:
                lines.append(f"- {key}: `{http[key]}`")
        for key in ["health", "products", "refresh_status"]:
            if key in http:
                value = http[key]
                lines.append(f"- {key}: ok=`{value.get('ok')}`, status=`{value.get('status')}`, error=`{value.get('error')}`")
        if "refresh_summary" in http:
            lines.append(f"- refresh_summary: `{json.dumps(http['refresh_summary'], ensure_ascii=False)}`")

    warnings = report.get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Project root to inspect")
    parser.add_argument("--backend-url", help="Backend base URL, for example http://127.0.0.1:3001")
    parser.add_argument("--frontend-url", help="Frontend URL, for example http://127.0.0.1:5174")
    parser.add_argument("--post-refresh", action="store_true", help="POST /api/products/refresh if backend is reachable")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    repo = inspect_repo(root)
    warnings: list[str] = []

    if not repo["has_root_package"]:
        warnings.append("No root package.json found. This may be a wrapper folder, not the real source tree.")
    if repo["uses_better_sqlite3"] and "22" not in json.dumps(repo["node_markers"]):
        warnings.append("better-sqlite3 detected but Node 22 is not declared in .nvmrc/.node-version/engines.")
    if not repo["has_refresh_route"]:
        warnings.append("No refresh route hint found. Confirm whether manual data refresh exists.")
    if repo["has_recharts"]:
        warnings.append("Recharts detected. Browser-test charts for zero-width/zero-height containers inside tabs.")

    report: dict[str, Any] = {"repo": repo, "warnings": warnings}
    if args.backend_url or args.frontend_url:
        report["http"] = probe_http(args.backend_url, args.frontend_url, args.post_refresh)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
