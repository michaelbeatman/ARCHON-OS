#!/usr/bin/env python3
"""Mathematically generated Silver Copperplate Clockwork, Multi-Layer Da-Vinci Gears & Zero-Egress SVGs.

Pixel-measured alignment for:
  1. Vertical S-Curve Da-Vinci Clockwork (764x1024) — Hero Right Stage
  2. Circular Da-Vinci Sovereign Wheel (1024x764) — FAQ / Lower Section Stage
  3. Standalone Animated Vector Silver Clockwork & Passkey Vault Lock — Governance Showcase
  4. Animated Zero-Egress & Governance Architecture Circuit Diagram
"""
from __future__ import annotations

import math


def gear_path(
    cx: float,
    cy: float,
    r_outer: float,
    r_root: float,
    teeth: int,
    tooth_ratio: float = 0.44,
    phase: float = 0.0,
) -> str:
    """Return an SVG path for a precision involute-style clockwork gear."""
    step = (2.0 * math.pi) / teeth
    pts: list[tuple[float, float]] = []
    for i in range(teeth):
        a0 = phase + i * step
        a1 = a0 + step * (0.5 - tooth_ratio * 0.5)
        a2 = a1 + step * 0.09
        a3 = a0 + step * (0.5 + tooth_ratio * 0.5) - step * 0.09
        a4 = a0 + step * (0.5 + tooth_ratio * 0.5)
        for r, a in (
            (r_root, a0),
            (r_root, a1),
            (r_outer, a2),
            (r_outer, a3),
            (r_root, a4),
        ):
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    cmds = [f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"]
    for x, y in pts[1:]:
        cmds.append(f"L {x:.2f} {y:.2f}")
    cmds.append("Z")
    return " ".join(cmds)


def radial_ticks(
    cx: float,
    cy: float,
    r1: float,
    r2: float,
    count: int,
    major_every: int = 4,
    r2_major: float | None = None,
) -> str:
    """Generate engraved compass/dial calibration ticks."""
    r2m = r2_major if r2_major is not None else r2 + 5.0
    parts: list[str] = []
    for i in range(count):
        a = (2.0 * math.pi * i) / count
        is_major = major_every > 0 and (i % major_every == 0)
        ro = r2m if is_major else r2
        x1, y1 = cx + r1 * math.cos(a), cy + r1 * math.sin(a)
        x2, y2 = cx + ro * math.cos(a), cy + ro * math.sin(a)
        cls = "eng-tick-major" if is_major else "eng-tick"
        parts.append(f'<line class="{cls}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    return "".join(parts)


def gear_spokes(
    cx: float,
    cy: float,
    r_inner: float,
    r_outer: float,
    spokes: int = 5,
) -> str:
    """Generate pierced horological clockwork spokes with rivets."""
    parts: list[str] = []
    for i in range(spokes):
        a = (2.0 * math.pi * i) / spokes
        x1, y1 = cx + r_inner * math.cos(a), cy + r_inner * math.sin(a)
        x2, y2 = cx + r_outer * math.cos(a), cy + r_outer * math.sin(a)
        parts.append(f'<line class="eng-spoke" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
        rm = (r_inner + r_outer) * 0.54
        rx, ry = cx + rm * math.cos(a), cy + rm * math.sin(a)
        parts.append(f'<circle class="eng-rivet" cx="{rx:.1f}" cy="{ry:.1f}" r="2.1"/>')
    return "".join(parts)


def build_davinci_vertical_underlayer_svg() -> str:
    """Layer 1 rotating silver gears pixel-aligned to davinci_vertical_*.webp (764x1024).

    Static copperplate frame, linkages, chains, Policy Engine scale & lock housings stay fixed
    in the foreground while these 9 precision gears counter-rotate smoothly underneath:
      - Gear A  (306, 128) R=49, 18T CW
      - Gear B  (260, 236) R=65, 24T CCW
      - Pinion B2 (348, 224) R=28, 12T CW
      - Dial C  (442, 324) BUDGET BANK escapement ring R=72, 30T CCW
      - Gear D  (262, 382) R=61, 22T CW
      - Pinion D2 (348, 384) R=26, 12T CCW
      - Wheel E (348, 488) R=45, 18T CW
      - Gear H  (388, 818) R=67, 24T CCW
      - Hub H2  (308, 818) R=26, 12T CW
      - Wheel I (310, 916) R=41, 16T CW
    """
    ga = gear_path(306, 128, 49, 41, 18, 0.44)
    gb = gear_path(260, 236, 65, 56, 24, 0.45)
    gb2 = gear_path(348, 224, 28, 22, 12, 0.44, 0.2)
    gc_ticks = radial_ticks(442, 324, 58, 66, 48, major_every=4, r2_major=71)
    gd = gear_path(262, 382, 61, 52, 22, 0.45, 0.12)
    gd2 = gear_path(348, 384, 26, 20, 12, 0.44)
    ge = gear_path(348, 488, 45, 38, 18, 0.44, 0.1)
    gh = gear_path(388, 818, 67, 58, 24, 0.45, 0.15)
    gh2 = gear_path(308, 818, 26, 20, 12, 0.44)
    gi = gear_path(310, 916, 41, 34, 16, 0.44, 0.12)

    return f"""<svg class="davinci-underlayer-svg" viewBox="0 0 764 1024" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <!-- Gear A: Upper-left inside main arch -->
  <g class="cw-gear cw-v-a" style="transform-origin:306px 128px">
    <path class="eng-under-gear-bright" d="{ga}"/>
    <circle class="eng-under-ring" cx="306" cy="128" r="35"/>
    {gear_spokes(306, 128, 11, 35, 5)}
  </g>
  <!-- Gear B: Upper-left large primary gear -->
  <g class="cw-gear cw-v-b" style="transform-origin:260px 236px">
    <path class="eng-under-gear-bright" d="{gb}"/>
    <circle class="eng-under-ring" cx="260" cy="236" r="49"/>
    {gear_spokes(260, 236, 16, 49, 6)}
  </g>
  <!-- Pinion B2: Center drive pinion -->
  <g class="cw-gear cw-v-b2" style="transform-origin:348px 224px">
    <path class="eng-under-gear-bright" d="{gb2}"/>
    <circle class="eng-under-ring" cx="348" cy="224" r="15"/>
  </g>
  <!-- Dial C: BUDGET BANK rotating inner chronometer ring -->
  <g class="cw-gear cw-v-dial" style="transform-origin:442px 324px">
    <circle class="eng-under-ring" cx="442" cy="324" r="71" stroke-dasharray="14 6 3 6"/>
    <circle class="eng-under-ring" cx="442" cy="324" r="56"/>
    {gc_ticks}
  </g>
  <!-- Gear D: Mid-left large gear -->
  <g class="cw-gear cw-v-d" style="transform-origin:262px 382px">
    <path class="eng-under-gear-bright" d="{gd}"/>
    <circle class="eng-under-ring" cx="262" cy="382" r="45"/>
    {gear_spokes(262, 382, 14, 45, 5)}
  </g>
  <!-- Pinion D2 -->
  <g class="cw-gear cw-v-d2" style="transform-origin:348px 384px">
    <path class="eng-under-gear-bright" d="{gd2}"/>
    <circle class="eng-under-ring" cx="348" cy="384" r="14"/>
  </g>
  <!-- Wheel E: Mid-center spoked gear -->
  <g class="cw-gear cw-v-e" style="transform-origin:348px 488px">
    <path class="eng-under-gear-bright" d="{ge}"/>
    <circle class="eng-under-ring" cx="348" cy="488" r="32"/>
    {gear_spokes(348, 488, 10, 32, 5)}
  </g>
  <!-- Gear H: Lower-right large gear -->
  <g class="cw-gear cw-v-h" style="transform-origin:388px 818px">
    <path class="eng-under-gear-bright" d="{gh}"/>
    <circle class="eng-under-ring" cx="388" cy="818" r="51"/>
    {gear_spokes(388, 818, 16, 51, 6)}
  </g>
  <!-- Hub H2: Lower center pinion -->
  <g class="cw-gear cw-v-h2" style="transform-origin:308px 818px">
    <path class="eng-under-gear-bright" d="{gh2}"/>
    <circle class="eng-under-ring" cx="308" cy="818" r="14"/>
  </g>
  <!-- Wheel I: Lower bottom spoked wheel -->
  <g class="cw-gear cw-v-i" style="transform-origin:310px 916px">
    <path class="eng-under-gear-bright" d="{gi}"/>
    <circle class="eng-under-ring" cx="310" cy="916" r="29"/>
    {gear_spokes(310, 916, 9, 29, 5)}
  </g>
</svg>"""


def build_davinci_vertical_overlay_svg() -> str:
    """Layer 3 foreground horological animations on davinci_vertical_*.webp (764x1024):
    - Sweeping BUDGET BANK watch hands pivoted at exact center (442, 324)
    - Oscillating silver tumbler rings around both Passkey keyhole locks (442, 488) & (226, 820)
    - Subtle silver orbital pulses along the top & bottom giant outer arcs
    """
    return """<svg class="davinci-overlay-svg" viewBox="0 0 764 1024" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <!-- Real sweeping chronometer hands on BUDGET BANK dial (442, 324) -->
  <g class="cw-hand-slow" style="transform-origin:442px 324px">
    <line class="eng-dial-hand-hour" x1="442" y1="336" x2="442" y2="278"/>
  </g>
  <g class="cw-hand-sweep" style="transform-origin:442px 324px">
    <line class="eng-dial-hand" x1="442" y1="340" x2="442" y2="262"/>
  </g>
  <circle class="eng-rivet-bright" cx="442" cy="324" r="4.2"/>

  <!-- Upper PASSKEY-GATE keyhole tumbler ring (442, 488) -->
  <g class="cw-tumbler" style="transform-origin:442px 488px">
    <circle class="eng-tumbler-ring" cx="442" cy="488" r="56" stroke-dasharray="18 12 4 12"/>
  </g>

  <!-- Lower Keyhole Lock tumbler ring (226, 820) -->
  <g class="cw-tumbler-rev" style="transform-origin:226px 820px">
    <circle class="eng-tumbler-ring" cx="226" cy="820" r="52" stroke-dasharray="16 12 4 12"/>
  </g>

  <!-- Subtle silver orbital light pulses along the giant upper & lower copperplate arcs -->
  <circle class="eng-telemetry-orbit" cx="354" cy="224" r="184"/>
  <circle class="eng-telemetry-orbit-rev" cx="304" cy="820" r="165"/>
</svg>"""


def build_davinci_underlayer_svg() -> str:
    """Layer 1 rotating silver gears aligned behind circular davinci_wheel_*.webp (1024x764) at FAQ."""
    main_gear = gear_path(500, 384, 276, 258, 48, tooth_ratio=0.44)
    main_ticks = radial_ticks(500, 384, 238, 248, 72, major_every=6, r2_major=254)
    upper_gear = gear_path(424, 200, 92, 80, 24, tooth_ratio=0.45)
    upper_spokes = gear_spokes(424, 200, 24, 72, 5)
    lower_gear = gear_path(498, 560, 86, 74, 22, tooth_ratio=0.45, phase=0.14)
    lower_spokes = gear_spokes(498, 560, 22, 66, 5)

    return f"""<svg class="davinci-underlayer-svg" viewBox="0 0 1024 764" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <g class="cw-gear cw-dv-main" style="transform-origin:500px 384px">
    <path class="eng-under-gear" d="{main_gear}"/>
    <circle class="eng-under-ring" cx="500" cy="384" r="246"/>
    {main_ticks}
  </g>
  <g class="cw-gear cw-dv-upper" style="transform-origin:424px 200px">
    <path class="eng-under-gear-bright" d="{upper_gear}"/>
    <circle class="eng-under-ring" cx="424" cy="200" r="72"/>
    {upper_spokes}
  </g>
  <g class="cw-gear cw-dv-lower" style="transform-origin:498px 560px">
    <path class="eng-under-gear-bright" d="{lower_gear}"/>
    <circle class="eng-under-ring" cx="498" cy="560" r="66"/>
    {lower_spokes}
  </g>
  <g class="cw-tumbler" style="transform-origin:676px 386px">
    <circle class="eng-tumbler-ring" cx="676" cy="386" r="94" stroke-dasharray="22 14 6 14"/>
    <circle class="eng-under-ring" cx="676" cy="386" r="76" stroke-dasharray="10 10"/>
  </g>
</svg>"""


def build_davinci_overlay_svg() -> str:
    """Layer 3 subtle foreground dial sweep hand over circular davinci_wheel_*.webp (1024x764) at FAQ."""
    return """<svg class="davinci-overlay-svg" viewBox="0 0 1024 764" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <g class="cw-hand-sweep" style="transform-origin:424px 200px">
    <line class="eng-dial-hand" x1="424" y1="214" x2="424" y2="132"/>
    <circle class="eng-rivet-bright" cx="424" cy="200" r="4"/>
  </g>
  <circle class="eng-telemetry-orbit" cx="500" cy="384" r="326"/>
</svg>"""


def build_hero_clockwork_svg() -> str:
    """Standalone precision animated Vector Silver Clockwork & Passkey Vault Lock SVG (Governance Showcase)."""
    g1_path = gear_path(410, 310, 173, 157, 36, tooth_ratio=0.45)
    g1_spokes = gear_spokes(410, 310, 86, 146, 6)
    g1_ticks = radial_ticks(410, 310, 146, 153, 72, major_every=6, r2_major=156)

    g2_path = gear_path(180, 178, 108, 92, 22, tooth_ratio=0.45, phase=0.14)
    g2_spokes = gear_spokes(180, 178, 28, 84, 5)
    g2_ticks = radial_ticks(180, 178, 76, 84, 44, major_every=4, r2_major=87)

    g3_path = gear_path(216, 486, 104, 88, 20, tooth_ratio=0.45, phase=0.16)
    g3_spokes = gear_spokes(216, 486, 26, 80, 5)
    g3_ticks = radial_ticks(216, 486, 72, 80, 40, major_every=4, r2_major=83)

    g4_path = gear_path(110, 336, 79, 65, 16, tooth_ratio=0.45, phase=0.08)
    g4_spokes = gear_spokes(110, 336, 18, 57, 4)

    outer_dial = radial_ticks(410, 310, 198, 206, 72, major_every=6, r2_major=214)

    return f"""<svg class="clockwork-svg" viewBox="0 0 640 650" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Archon OS Animated Silver Clockwork and Passkey Vault Lock">
  <defs>
    <pattern id="cw-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(35)">
      <line x1="0" y1="0" x2="0" y2="8" stroke="currentColor" stroke-width="0.6" stroke-opacity="0.22"/>
    </pattern>
    <radialGradient id="cw-glow" cx="64%" cy="47%" r="48%">
      <stop offset="0%" stop-color="var(--silver-bright)" stop-opacity="0.09"/>
      <stop offset="100%" stop-color="var(--silver)" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <circle cx="410" cy="310" r="244" fill="url(#cw-glow)"/>

  <g class="eng-construction">
    <circle cx="410" cy="310" r="224" stroke-dasharray="3 6"/>
    <circle cx="410" cy="310" r="196"/>
    <line x1="410" y1="54" x2="410" y2="108" stroke-dasharray="2 4"/>
    <line x1="410" y1="512" x2="410" y2="574" stroke-dasharray="2 4"/>
    <line x1="158" y1="310" x2="210" y2="310" stroke-dasharray="2 4"/>
    <line x1="606" y1="310" x2="634" y2="310" stroke-dasharray="2 4"/>
    {outer_dial}
  </g>

  <circle class="eng-telemetry-orbit" cx="410" cy="310" r="211"/>
  <path class="eng-telemetry-trace" d="M 180 178 L 410 310 L 216 486 L 110 336 Z"/>

  <g class="cw-gear cw-g4" style="transform-origin:110px 336px">
    <path class="eng-gear-silver" d="{g4_path}"/>
    <circle class="eng-ring" cx="110" cy="336" r="57"/>
    <circle class="eng-ring" cx="110" cy="336" r="18"/>
    {g4_spokes}
    <circle class="eng-hub" cx="110" cy="336" r="6"/>
  </g>

  <g class="cw-gear cw-g2" style="transform-origin:180px 178px">
    <path class="eng-gear-steel" d="{g2_path}"/>
    <circle class="eng-ring" cx="180" cy="178" r="84"/>
    <circle class="eng-ring-hatch" cx="180" cy="178" r="76" fill="url(#cw-hatch)"/>
    <circle class="eng-ring" cx="180" cy="178" r="28"/>
    {g2_ticks}
    {g2_spokes}
    <circle class="eng-hub" cx="180" cy="178" r="8"/>
  </g>

  <g class="cw-gear cw-g3" style="transform-origin:216px 486px">
    <path class="eng-gear-silver" d="{g3_path}"/>
    <circle class="eng-ring" cx="216" cy="486" r="80"/>
    <circle class="eng-ring" cx="216" cy="486" r="71"/>
    <circle class="eng-ring" cx="216" cy="486" r="26"/>
    {g3_ticks}
    {g3_spokes}
    <circle class="eng-hub" cx="216" cy="486" r="8"/>
  </g>

  <g class="cw-gear cw-g1" style="transform-origin:410px 310px">
    <path class="eng-gear-silver-main" d="{g1_path}"/>
    <circle class="eng-ring-strong" cx="410" cy="310" r="146"/>
    <circle class="eng-ring" cx="410" cy="310" r="136"/>
    <circle class="eng-ring" cx="410" cy="310" r="88"/>
    {g1_ticks}
    {g1_spokes}
  </g>

  <g class="eng-lock-assembly">
    <circle class="eng-lock-plate" cx="410" cy="310" r="78"/>
    <circle class="eng-lock-bezel" cx="410" cy="310" r="70" stroke-dasharray="10 4 2 4"/>
    <g class="cw-tumbler" style="transform-origin:410px 310px">
      <circle class="eng-tumbler-ring" cx="410" cy="310" r="56" stroke-dasharray="28 12 10 10"/>
      <circle class="eng-tumbler-accent" cx="410" cy="310" r="46" stroke-dasharray="16 14 4 14"/>
    </g>
    <path class="eng-escutcheon" d="M 410 264 C 428 264 440 276 440 292 C 440 302 435 310 428 316 L 434 352 C 426 358 394 358 386 352 L 392 316 C 385 310 380 302 380 292 C 380 276 392 264 410 264 Z"/>
    <path class="eng-keyhole" d="M 410 280 A 13 13 0 1 1 402 303 L 396 338 L 424 338 L 418 303 A 13 13 0 0 1 410 280 Z"/>
    <circle class="eng-rivet-bright" cx="410" cy="242" r="2.6"/>
    <circle class="eng-rivet-bright" cx="410" cy="378" r="2.6"/>
    <circle class="eng-rivet-bright" cx="342" cy="310" r="2.6"/>
    <circle class="eng-rivet-bright" cx="478" cy="310" r="2.6"/>
  </g>

  <g class="eng-labels">
    <line x1="180" y1="68" x2="180" y2="44"/>
    <line x1="180" y1="44" x2="310" y2="44"/>
    <text x="186" y="38">I. POLICY ENGINE</text>

    <line x1="468" y1="118" x2="496" y2="86"/>
    <line x1="496" y1="86" x2="612" y2="86"/>
    <text x="498" y="80">II. PASSKEY LOCK</text>

    <line x1="216" y1="590" x2="216" y2="616"/>
    <line x1="216" y1="616" x2="386" y2="616"/>
    <text x="222" y="610">III. ATOMIC BUDGETBANK</text>

    <text class="eng-label-muted" x="355" y="556">ZERO-EGRESS · SHA-256</text>
  </g>
</svg>"""


def build_zero_egress_diagram_svg(lang: str = "en", labels: dict[str, str] | None = None) -> str:
    """Monochrome Silver Zero-Egress & Governance Architecture Circuit Diagram (all 11 languages)."""
    is_de = lang == "de"
    lb = labels or {}
    t_req = lb.get("req") or ("Anfrage / Agent" if is_de else "Task / Agent Call")
    t_pol = "PolicyEngine"
    t_pol_sub = lb.get("polSub") or ("Default-Deny &amp; HMAC-Warrant" if is_de else "Default-Deny &amp; HMAC Warrant")
    t_bud = "Atomic BudgetBank"
    t_bud_sub = lb.get("budSub") or ("BEGIN IMMEDIATE Reservierung" if is_de else "BEGIN IMMEDIATE Reservation")
    t_sw = lb.get("sw") or ("OmniRoute Weiche" if is_de else "OmniRoute Switch")
    t_sw_sub = lb.get("swSub") or ("Fail-Closed Klassifikation" if is_de else "Fail-Closed Classification")
    t_loc = lb.get("loc") or ("ZERO-EGRESS LOKAL" if is_de else "ZERO-EGRESS LOCAL")
    t_loc_sub = lb.get("locSub") or ("Ollama / LM Studio · Kein Internet" if is_de else "Ollama / LM Studio · No Internet")
    t_cld = lb.get("cld") or ("Cloud-LLMs (nur unkritisch)" if is_de else "Cloud LLMs (non-sensitive)")
    t_cld_sub = lb.get("cldSub") or ("Budget-gedeckelt · PII-gefiltert" if is_de else "Budget-capped · PII-scrubbed")
    t_hitl = "Passkey / WebAuthn HITL"
    t_hitl_sub = lb.get("hitlSub") or ("Kryptografische Freigabe" if is_de else "Cryptographic Human Sign-Off")
    t_aud = "SHA-256 Audit-Chain"
    t_aud_sub = lb.get("audSub") or "GoBD · EU AI Act · Effect-Ledger"

    return f"""<svg class="arch-flow-svg" viewBox="0 0 980 310" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Archon OS Zero-Egress Architecture Flow">
  <defs>
    <marker id="arr-sil" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--silver-bright)"/>
    </marker>
    <marker id="arr-em" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--emerald)"/>
    </marker>
  </defs>

  <rect class="arch-zone-local" x="536" y="18" width="218" height="122" rx="12"/>
  <text class="arch-zone-tag" x="550" y="38">DOCKER INTERNAL NET (NO EGRESS)</text>

  <path class="arch-rail" d="M 148 152 L 194 152"/>
  <path class="arch-pulse arch-pulse-silver" d="M 148 152 L 194 152" marker-end="url(#arr-sil)"/>

  <path class="arch-rail" d="M 342 152 L 386 152"/>
  <path class="arch-pulse arch-pulse-silver" d="M 342 152 L 386 152" marker-end="url(#arr-sil)"/>

  <path class="arch-rail" d="M 498 128 C 516 128 518 88 548 88"/>
  <path class="arch-pulse arch-pulse-em" d="M 498 128 C 516 128 518 88 548 88" marker-end="url(#arr-em)"/>

  <path class="arch-rail" d="M 498 176 C 516 176 518 228 548 228"/>
  <path class="arch-pulse arch-pulse-silver" d="M 498 176 C 516 176 518 228 548 228" marker-end="url(#arr-sil)"/>

  <path class="arch-rail" d="M 740 88 C 770 88 770 112 796 112"/>
  <path class="arch-pulse arch-pulse-em" d="M 740 88 C 770 88 770 112 796 112" marker-end="url(#arr-em)"/>

  <path class="arch-rail" d="M 740 228 C 770 228 770 218 796 218"/>
  <path class="arch-pulse arch-pulse-silver" d="M 740 228 C 770 228 770 218 796 218" marker-end="url(#arr-sil)"/>

  <path class="arch-rail" d="M 880 144 L 880 184"/>
  <path class="arch-pulse arch-pulse-silver" d="M 880 144 L 880 184" marker-end="url(#arr-sil)"/>

  <g class="arch-node">
    <rect x="16" y="116" width="132" height="72" rx="10"/>
    <text class="arch-node-title" x="82" y="148" text-anchor="middle">{t_req}</text>
    <text class="arch-node-sub" x="82" y="168" text-anchor="middle">70 Profiles · MCP</text>
  </g>

  <g class="arch-node arch-node-silver">
    <rect x="196" y="88" width="146" height="58" rx="10"/>
    <text class="arch-node-title" x="269" y="114" text-anchor="middle">{t_pol}</text>
    <text class="arch-node-sub" x="269" y="132" text-anchor="middle">{t_pol_sub}</text>
  </g>
  <g class="arch-node arch-node-silver">
    <rect x="196" y="160" width="146" height="58" rx="10"/>
    <text class="arch-node-title" x="269" y="186" text-anchor="middle">{t_bud}</text>
    <text class="arch-node-sub" x="269" y="204" text-anchor="middle">{t_bud_sub}</text>
  </g>

  <g class="arch-node arch-node-silver">
    <rect x="388" y="112" width="110" height="80" rx="10"/>
    <text class="arch-node-title" x="443" y="146" text-anchor="middle">{t_sw}</text>
    <text class="arch-node-sub" x="443" y="166" text-anchor="middle">{t_sw_sub}</text>
  </g>

  <g class="arch-node arch-node-emerald">
    <rect x="550" y="52" width="190" height="72" rx="10"/>
    <text class="arch-node-title" x="645" y="83" text-anchor="middle">{t_loc}</text>
    <text class="arch-node-sub" x="645" y="103" text-anchor="middle">{t_loc_sub}</text>
  </g>

  <g class="arch-node">
    <rect x="550" y="192" width="190" height="72" rx="10"/>
    <text class="arch-node-title" x="645" y="223" text-anchor="middle">{t_cld}</text>
    <text class="arch-node-sub" x="645" y="243" text-anchor="middle">{t_cld_sub}</text>
  </g>

  <g class="arch-node arch-node-silver">
    <rect x="798" y="76" width="166" height="68" rx="10"/>
    <text class="arch-node-title" x="881" y="106" text-anchor="middle">{t_hitl}</text>
    <text class="arch-node-sub" x="881" y="125" text-anchor="middle">{t_hitl_sub}</text>
  </g>

  <g class="arch-node arch-node-silver">
    <rect x="798" y="186" width="166" height="68" rx="10"/>
    <text class="arch-node-title" x="881" y="216" text-anchor="middle">{t_aud}</text>
    <text class="arch-node-sub" x="881" y="235" text-anchor="middle">{t_aud_sub}</text>
  </g>
</svg>"""
