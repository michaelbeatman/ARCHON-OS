# -*- coding: utf-8 -*-
"""Stage-1-Reaudit Runde G — verbleibende Frontend-MED-Funde.

Statische Regressionstests (kein Build, keine Migration, kein Replay) fuer:
  D01  PbSettingsModal: Fake-Save der Application-Toggles
  D08  fehlendes AbortController / fehlende Fensterung (bereits gehärtet)
  D09  Fokus-Trap / XSS-Senken (bereits gehärtet, CSS-Sink nachgezogen)
  D16  Browser-Kontext und Trace-Header an allen same-origin Fetch-Stellen

Nicht in diesem Scope: backend-/scripts-/CI-Funde aus D06, D09, D16.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------- D01

def test_d01_application_toggles_are_not_saved_as_success():
    """Die fuenf wirkungslosen Controls duerfen keinen Erfolg suggerieren."""
    src = _src("frontend/src/components/PbSettingsModal.tsx")

    # Keine Setter mehr: die Werte sind bewusst nicht bedienbar/persistierbar.
    for state in (
        "[accentColor]", "[batchApiEnabled]", "[ipProxyEnabled]", "[rateLimitingEnabled]"
    ):
        assert f"const {state} = useState" in src
    assert "setAccentColor" not in src
    assert "setBatchApiEnabled" not in src
    assert "setIpProxyEnabled" not in src
    assert "setRateLimitingEnabled" not in src
    assert "rateLimitMax" not in src.replace(
        "// und rateLimitMax haben keinen Backend-Endpunkt. Sie bleiben absichtlich", ""
    )

    # Ehrlicher Hinweis + disability an jeder sichtbaren Control.
    assert "Hinweis: Es werden nur Name und URL gespeichert." in src
    assert src.count("nicht konfigurierbar") >= 4
    assert src.count("disabled") >= 4

    # Persistiert wird ausschliesslich appName/appUrl.
    assert "await pb.settings.update({ meta: { appName, appUrl } });" in src
    assert "'Name & URL gespeichert'" in src
    assert "<span>Gespeichert!</span>" not in src


def test_d01_smtp_requires_explicit_backend_status():
    """HTTP 200 mit status:'error' darf nicht als Erfolg gerendert werden."""
    src = _src("frontend/src/components/PbSettingsModal.tsx")
    assert "archonFetch<{ status?: string; message?: string }>(" in src
    assert "'api/v1/settings/smtp'," in src
    assert "if (data?.status === 'error')" in src
    assert "if (data?.status === 'success')" in src
    assert "await fetch('/api/v1/settings/smtp'" not in src


# ----------------------------------------------------------------- D16 / D08

TRACED_COMPONENTS = (
    "GatewayManagerModal.tsx",
    "WatchdogModal.tsx",
    "UnifiedAgentControlPanel.tsx",
    "SidebarNav.tsx",
    "MissionControlView.tsx",
    "CssLiveStudio.tsx",
    "KontaktDrawer.tsx",
    "CalendarView.tsx",
)


def test_d16_central_traced_fetch_wrapper():
    """Alle Browser-Requests gehen durch einen W3C-Header-Wrapper."""
    api = _src("frontend/src/lib/archon-api.ts")
    assert "export function createTraceparent()" in api
    assert "crypto.getRandomValues" in api
    assert "return `00-${traceId}-${spanId}-01`;" in api
    assert "export function withTraceHeaders(init?: RequestInit): RequestInit" in api
    assert "export async function tracedFetch(url: string, init?: RequestInit): Promise<Response>" in api
    assert "fetch(url, withTraceHeaders(init))" in api
    assert "setArchonTracestate(res.headers.get('tracestate'))" in api


def test_d16_no_raw_browser_fetch_in_traced_components():
    """Same-origin-Komponenten duerfen nicht mehr direkt fetch() aufrufen."""
    for name in TRACED_COMPONENTS:
        src = _src(f"frontend/src/components/{name}")
        assert 'from "@/lib/archon-api"' in src or "from '@/lib/archon-api'" in src, name
        # Nur Same-Origin-API-Calls müssen über tracedFetch laufen.
        # `fetch(data:image/...)` (Blob-Konvertierung) und Cross-Origin-
        # Aggregator-Calls (CORS/Preflight) bleiben bewusst unangetastet.
        assert not re.search(r"(?<!traced)fetch\(\s*['\"`]/?api/", src), name


def test_d16_proxy_and_sse_carry_browser_context():
    """Der Next.js-Proxy forkte den Browser-Kontext; SSE nutzt einen Query-Fallback."""
    proxy = _src("frontend/src/app/api/archon/[...path]/route.ts")
    assert "function rootTraceparent()" in proxy
    assert "const forkedTp = childTraceparent(rawTp);" in proxy
    assert "forwardHeaders['traceparent'] = outgoingTp;" in proxy

    theme = _src("frontend/src/app/api/theme/live_overrides/route.ts")
    assert "headers['traceparent'] = traceparent;" in theme

    sse = _src("frontend/src/lib/useArchonEvents.ts")
    assert sse.count("new EventSource(") == 1  # genau EIN geteilter Bus
    assert "url.searchParams.set('traceparent', createTraceparent());" in sse


def test_d08_abort_controllers_and_template_window():
    """Bereits gehärtete D08-Funde bleiben regressiv geschützt."""
    cockpit = _src("frontend/src/components/WorkflowCockpit.tsx")
    assert "new AbortController()" in cockpit
    assert "return () => controller.abort();" in cockpit
    assert "templates.slice(0, tplVisibleCount)" in cockpit

    panel = _src("frontend/src/components/UnifiedAgentControlPanel.tsx")
    assert "sendAbortRef.current?.abort()" in panel

    gateway = _src("frontend/src/components/GatewayManagerModal.tsx")
    assert "return () => controller.abort();" in gateway

    watchdog = _src("frontend/src/components/WatchdogModal.tsx")
    assert "void fetchConfig(controller.signal);" in watchdog
    assert "return () => controller.abort();" in watchdog

    sidebar = _src("frontend/src/components/SidebarNav.tsx")
    assert sidebar.count("new AbortController()") == 2

    settings_modal = _src("frontend/src/components/PbSettingsModal.tsx")
    assert "const controller = new AbortController();" in settings_modal
    assert "if (controller.signal.aborted) return;" in settings_modal


# --------------------------------------------------------------------- D09

def test_d09_dialog_semantics_and_sanitized_html_sinks():
    auth = _src("frontend/src/components/AuthModal.tsx")
    assert 'role="dialog"' in auth
    assert 'aria-modal="true"' in auth
    assert "event.key === 'Escape'" in auth
    assert "previousFocus?.focus()" in auth

    crm = _src("frontend/src/app/crm/page.tsx")
    assert "dangerouslySetInnerHTML={{ __html: safeSvg }}" in crm
    design = _src("frontend/src/components/DesignEditorTab.tsx")
    assert "dangerouslySetInnerHTML={{ __html: safeSvg }}" in design

    # Zustaetzlicher, zuvor unsanitisierter CSS-innerHTML-Sink.
    css = _src("frontend/src/components/CssLiveStudio.tsx")
    assert "function sanitizeCssSink(css: string): string" in css
    assert "styleTag.innerHTML = sanitizeCssSink(cssText);" in css
    assert "@import" in css and "javascript|data" in css


def test_frontend_toolchain_contract():
    pkg = json.loads(_src("frontend/package.json"))
    assert pkg["scripts"]["test"]
    assert "sanitizeSvg.test.mjs" in pkg["scripts"]["test"]
    cfg = json.loads(_src("frontend/tsconfig.json"))
    assert cfg["compilerOptions"]["strict"] is True
    assert cfg["compilerOptions"]["noEmit"] is True
