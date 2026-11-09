#!/usr/bin/env python3
"""AST-Audit: Routen x Methoden x Rollenzaun (Security-Review 2026-11-08).

Zaehlt alle Routen-Deklarationen in den HTTP-Schichten und prueft je
(Methode, Pfad)-Paar, ob im Funktionsrumpf ein Rollenzaun-Aufruf steht.

Zaehlregel (bewusst eng, damit die Zahl nicht schoenrechnet):

  Routen-Quelle : AST der Dekoratoren `@app.<verb>`, `@<router>.<verb>`,
                  `@<router>.api_route(...)` in
                  main.py, archon/routers/*.py (ausser _rbac.py),
                  views_core.py, backend/operations_api.py und
                  jedem backend/*.py mit APIRouter(...).
  Einheit       : (Datei, Zeile, Methode, Pfad).  Ein `api_route` mit
                  methods=["GET","POST"] ergibt ZWEI Einheiten.
  mutierend     : Methode in {POST, PUT, PATCH, DELETE}.
  geschuetzt    : im Rumpf der Handler-Funktion steht ein Aufruf eines
                  Namens, der auf einen Rollenzaun passt:
                    * require_admin, require_admin_or_503, _require_admin,
                      require_role, require_admin_role, ensure_admin
                    * Depends(<guard>) in der Signatur
                    * ein `role != "admin"` / `role not in {...}`-Vergleich
                      gegen eine per get_current_user*() geholte Identitaet
                  Nur der Name zaehlt; ob der Guard wirklich sperrt, ist
                  eine manuelle Frage (siehe Befundliste im Review).
  Sonstiges     : Methoden GET/HEAD/OPTIONS gelten als lesend und werden
                  separat gezaehlt (nicht als "ohne Zaun"-Befund).

  Grenze der Zaehlung: der Guard wird am HANDLER erkannt, nicht je Methode.
  Ein `api_route(methods=[...])` mit einem unbedingten Guard gilt damit fuer
  alle Methoden als geschuetzt. Das ist hier zulaessig, weil KEIN Handler im
  Bestand auf `request.method` verzweigt (Gegenprobe: 0 Treffer fuer
  `request.method ==` in main.py, views_core.py, archon/, backend/). Sobald
  ein Handler methodenabhaengig prueft, muss diese Zaehlung nachgezogen
  werden — sonst zaehlt sie eine Verzweigung als Schutz fuer alle Methoden.

Aufruf:
    .venv/bin/python scripts/audit_route_guards.py [--root .] [--json out.json]
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
READING = {"GET", "HEAD", "OPTIONS"}
GUARD_NAMES = {
    "require_admin",
    "require_admin_or_503",
    "_require_admin",
    "require_role",
    "require_admin_role",
    "ensure_admin",
    "require_admin_dep",
}
ROUTE_VERBS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}


def _decorator_info(dec: ast.AST):
    """Liefert (method_list, path) oder None, wenn es keine Route ist."""
    if not isinstance(dec, ast.Call):
        return None
    fn = dec.func
    if not isinstance(fn, ast.Attribute) or fn.attr not in ROUTE_VERBS:
        return None
    path = None
    if dec.args and isinstance(dec.args[0], ast.Constant):
        path = dec.args[0].value
    methods = None
    if fn.attr == "api_route":
        methods = None
        for kw in dec.keywords:
            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                methods = [
                    e.value.upper()
                    for e in kw.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
        if not methods:
            methods = ["GET"]
    else:
        methods = [fn.attr.upper()]
    return methods, path


def _has_guard(fn: ast.AST) -> tuple[bool, list[str]]:
    hits: list[str] = []
    # Signatur: Depends(<guard>) / Parameter mit Guard-Default
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name in GUARD_NAMES:
                hits.append(f"{name}@{node.lineno}")
            elif name == "Depends":
                for a in list(node.args) + [k.value for k in node.keywords]:
                    inner = a.id if isinstance(a, ast.Name) else getattr(a, "attr", "")
                    if inner in GUARD_NAMES:
                        hits.append(f"Depends({inner})@{node.lineno}")
        elif isinstance(node, ast.Attribute) and node.attr in GUARD_NAMES:
            hits.append(f"{node.attr}@{node.lineno}")
        # Inline-Rollenvergleich
        elif isinstance(node, ast.Compare):
            src = ast.dump(node)
            if '"admin"' in src or "'admin'" in src:
                if "role" in src:
                    hits.append(f"role-compare@{node.lineno}")
    return (len(hits) > 0, hits)


def _first_stmt_guard(fn: ast.AST) -> bool:
    """Steht der Zaun wirklich am Anfang? Docstring zaehlt nicht als Anweisung.

    Nötig, weil `_has_guard` jede Erwähnung im Rumpf zählt: ein
    `require_admin(...)` nach `open(...)` schützt nichts mehr, wird aber
    fälschlich als "geschützt" gezählt. Damit die Kennzahl nicht schönrechnet,
    wird in der Ausgabe zwischen "Zaun = erste Anweisung" und "Zaun später"
    getrennt.
    """
    body = list(getattr(fn, "body", []))
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return False
    ok, _ = _has_guard(body[0])
    if ok:
        return True
    # `try:` als erste Anweisung: dann muss der Zaun die erste Anweisung im try-Rumpf sein
    if isinstance(body[0], ast.Try) and body[0].body:
        ok, _ = _has_guard(body[0].body[0])
        if ok:
            return True
    # Depends(<guard>) in der Signatur gilt ebenfalls als Zaun vor dem Rumpf
    for node in ast.walk(fn.args):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Depends":
            for a in list(node.args) + [k.value for k in node.keywords]:
                inner = a.id if isinstance(a, ast.Name) else getattr(a, "attr", "")
                if inner in GUARD_NAMES:
                    return True
    # try/except-Block, dessen erster Rumpf mit dem Zaun beginnt (verbreitetes Muster)
    return False


def _router_prefix(tree: ast.AST) -> str:
    """Liest `router = APIRouter(prefix="/api/operations")` der Datei.

    Ohne diesen Prefix steht in jeder Zeile eines Routers nur der Teilpfad
    (`/kanban/tasks`) statt des echten Pfads (`/api/operations/kanban/tasks`) —
    damit ist die Frage "liegt die Route hinter dem Auth-Gate?" nicht
    beantwortbar. Genau dieser Fehler steckte in der ersten Fassung.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if fname != "APIRouter":
            continue
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value or "")
    return ""


def scan_file(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read(), filename=path)
    except SyntaxError as exc:
        print(f"[WARN] SyntaxError {path}: {exc}", file=sys.stderr)
        return []
    prefix = _router_prefix(tree)
    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            info = _decorator_info(dec)
            if not info:
                continue
            methods, rpath = info
            if rpath is not None:
                rpath = str(rpath)
            if rpath and prefix and rpath.startswith("/"):
                rpath = prefix.rstrip("/") + rpath
            elif prefix and not rpath:
                rpath = prefix
            guarded, hits = _has_guard(node)
            gfirst = _first_stmt_guard(node)
            for m in methods:
                rows.append(
                    {
                        "file": path,
                        "line": dec.lineno,
                        "func_line": node.lineno,
                        "handler": node.name,
                        "method": m,
                        "path": rpath,
                        "mutating": m in MUTATING,
                        "guarded": guarded,
                        "guard_first": gfirst,
                        "guard_hits": hits,
                    }
                )
    return rows


def discover(root: str) -> list[str]:
    files = []
    for name in ("main.py", "views_core.py", "backend/operations_api.py"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            files.append(p)
    rd = os.path.join(root, "archon", "routers")
    if os.path.isdir(rd):
        for f in sorted(os.listdir(rd)):
            if f.endswith(".py") and f != "_rbac.py":
                files.append(os.path.join(rd, f))
    bd = os.path.join(root, "backend")
    if os.path.isdir(bd):
        for f in sorted(os.listdir(bd)):
            if not f.endswith(".py"):
                continue
            p = os.path.join(bd, f)
            if p in files:
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    if "APIRouter(" in fh.read():
                        files.append(p)
            except OSError:
                continue
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", default=None)
    ap.add_argument("--list", action="store_true", help="ungeschuetzte mutierende Routen ausgeben")
    args = ap.parse_args()

    rows = []
    for f in discover(args.root):
        rows.extend(scan_file(f))

    # Sammel-Schranken auf Router-Ebene: APIRouter(dependencies=[Depends(...)])
    # wuerde alle Routen der Datei schuetzen, ohne im Handler aufzutauchen.
    router_deps = []
    for f in discover(args.root):
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                tree = ast.parse(fh.read(), filename=f)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
                if any(kw.arg == "dependencies" for kw in node.keywords):
                    router_deps.append(f"{f}:{node.lineno}")

    total = len(rows)
    mut = [r for r in rows if r["mutating"]]
    read = [r for r in rows if not r["mutating"]]
    mut_guarded = [r for r in mut if r["guarded"]]
    mut_first = [r for r in mut if r.get("guard_first")]
    mut_late = [r for r in mut if r["guarded"] and not r.get("guard_first")]
    mut_open = [r for r in mut if not r["guarded"]]
    read_guarded = [r for r in read if r["guarded"]]

    # Auth-Gate-Abdeckung (Spiegel von archon/core/constants.py + main.py Middleware)
    public_prefixes = ("/static/", "/api/auth/login", "/api/auth/status", "/docs", "/redoc")
    protected_prefixes = ("/omniroute-proxy", "/n8n-proxy", "/rest/", "/hud", "/mobile", "/m", "/v2")
    public_exact = {"/", "/health", "/metrics", "/favicon.ico", "/openapi.json", "/login", "/docs", "/redoc"}

    def gate_status(p: str) -> str:
        p = p or ""
        if p in public_exact or p.startswith(public_prefixes):
            return "public"
        if p.startswith("/api/") or p.startswith(protected_prefixes):
            return "gate"      # 401 fuer /api/*, 307 fuer protected prefixes
        return "outside"       # Middleware laesst alles andere ungeprueft durch

    mut_gate = [r for r in mut_open if gate_status(r["path"]) == "gate"]
    mut_outside = [r for r in mut_open if gate_status(r["path"]) == "outside"]
    mut_public = [r for r in mut_open if gate_status(r["path"]) == "public"]

    # Destruktive Methoden und Catch-all-Pfade separat, weil sie die
    # Schaeden sind, die ein fehlender Zaun wirklich verursacht.
    mut_delete = [r for r in mut if r["method"] == "DELETE"]
    delete_open = [r for r in mut_delete if not r["guarded"]]
    catch_all = [r for r in rows if "{path:path}" in (r["path"] or "")]
    catch_all_open = [r for r in catch_all if r["mutating"] and not r["guarded"]]

    # api_route mit gemischten Methoden
    api_route_mixed = {}
    for r in rows:
        key = (r["file"], r["line"])
        api_route_mixed.setdefault(key, set()).add(r["method"])
    mixed = {k: v for k, v in api_route_mixed.items() if len(v) > 1}

    print(f"Routen-Einheiten (Methode x Pfad): {total}")
    print(f"  davon mutierend:                {len(mut)}")
    print(f"  davon lesend:                   {len(read)}")
    print(f"mutierend MIT Zaun:               {len(mut_guarded)}")
    print(f"  davon Zaun = erste Anweisung:   {len(mut_first)}")
    print(f"  davon Zaun erst spaeter:        {len(mut_late)}")
    print(f"mutierend OHNE Zaun:              {len(mut_open)}")
    print(f"  davon nur Auth-Gate (/api):     {len(mut_gate)}")
    print(f"  davon UNGEPRUEFT (ausserhalb):  {len(mut_outside)}")
    print(f"  davon oeffentlich (public):     {len(mut_public)}")
    print(f"DELETE gesamt (ohne Zaun):        {len(mut_delete)} ({len(delete_open)})")
    print(f"Catch-all {{path:path}} (mut., ohne Zaun): {len(catch_all)} ({len(catch_all_open)})")
    print(f"lesend MIT Zaun:                  {len(read_guarded)}")
    print(f"api_route mit >1 Methode:         {len(mixed)}")
    print(f"APIRouter(dependencies=...):      {len(router_deps)} {router_deps}")
    print()
    if mut_outside:
        print("mutierend OHNE Zaun UND ausserhalb des Auth-Gates:")
        for r in sorted(mut_outside, key=lambda x: (x["file"], x["line"])):
            print(f"  {r['file']}:{r['line']} {r['method']:6s} {r['path']}")
    if mut_public:
        print("mutierend OHNE Zaun UND unter public-Prefix:")
        for r in sorted(mut_public, key=lambda x: (x["file"], x["line"])):
            print(f"  {r['file']}:{r['line']} {r['method']:6s} {r['path']}")
    print()
    by_file = {}
    for r in mut_open:
        by_file[r["file"]] = by_file.get(r["file"], 0) + 1
    print("mutierend OHNE Zaun je Datei:")
    for f, n in sorted(by_file.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {f}")

    if args.list:
        print("\n-- ungeschuetzte mutierende Routen --")
        for r in sorted(mut_open, key=lambda x: (x["file"], x["line"])):
            print(f"{r['file']}:{r['line']} {r['method']:6s} {r['path']}  ({r['handler']})")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "rows": rows,
                    "summary": {
                        "total": total,
                        "mutating": len(mut),
                        "reading": len(read),
                        "mutating_guarded": len(mut_guarded),
                        "mutating_guarded_first_stmt": len(mut_first),
                        "mutating_guard_late": len(mut_late),
                        "mutating_open": len(mut_open),
                        "mutating_open_gate_only": len(mut_gate),
                        "mutating_open_outside": len(mut_outside),
                        "mutating_open_public": len(mut_public),
                        "delete_total": len(mut_delete),
                        "delete_open": len(delete_open),
                        "catch_all_total": len(catch_all),
                        "catch_all_open_mutating": len(catch_all_open),
                        "reading_guarded": len(read_guarded),
                        "api_route_multi_method": len(mixed),
                        "router_level_dependencies": router_deps,
                    },
                },
                fh,
                ensure_ascii=False,
                indent=1,
            )
        print(f"\nJSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
