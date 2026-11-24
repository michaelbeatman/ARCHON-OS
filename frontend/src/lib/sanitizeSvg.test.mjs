/**
 * F-068 / F-069 Regressionstest für den gemeinsamen SVG-Sanitizer.
 *
 * Lauf (Node 22+ mit TypeScript-Stripping):
 *   node --test frontend/src/lib/sanitizeSvg.test.mjs
 *
 * Der zentrale Fall ist der Audit-Payload `<svg onload=alert(1)>`: der
 * Event-Handler darf niemals im `dangerouslySetInnerHTML`-HTML landen.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { sanitizeSvgIcon, isSvgIcon } from './sanitizeSvg.ts';

test('Regression: <svg onload=alert(1)> wird entschärft', () => {
  const out = sanitizeSvgIcon('<svg onload=alert(1)><circle cx="5" cy="5" r="4"/></svg>');
  assert.equal(out.includes('onload'), false);
  assert.equal(out.includes('alert'), false);
  assert.match(out, /^<svg[\s>]/);
  assert.match(out, /<circle /);
});

test('Gross-/Kleinschreibung bei Event-Handlern ist egal', () => {
  const out = sanitizeSvgIcon('<svg ONLOAD="alert(1)" onClick="x()"><path d="M0 0"/></svg>');
  assert.equal(/onload|onclick|alert/i.test(out), false);
});

test('Gefährliche Tags und ihr Inhalt werden entfernt', () => {
  const out = sanitizeSvgIcon('<svg><script>alert(1)</script><foreignObject><iframe src="x"/></foreignObject><path d="M1 1"/></svg>');
  assert.equal(/script|foreignObject|iframe/i.test(out), false);
  assert.match(out, /<path d="M1 1"/);
});

test('javascript:/data:-URLs und CSS-Injektion werden entfernt', () => {
  const out = sanitizeSvgIcon(
    '<svg><a href="javascript:alert(1)"><use xlink:href="data:text/html,<script>x</script>"/></a>' +
    '<circle cx="1" cy="1" r="1" style="background:url(javascript:alert(1))"/></svg>',
  );
  assert.equal(/javascript:|data:|<script|style=/i.test(out), false);
});

test('Interne Fragment-Referenzen bleiben erhalten', () => {
  const out = sanitizeSvgIcon('<svg viewBox="0 0 24 24"><use href="#icon-a"/></svg>');
  assert.match(out, /viewBox="0 0 24 24"/);
  assert.match(out, /href="#icon-a"/);
});

test('Harmloses Icon bleibt unverändert nutzbar', () => {
  const raw = '<svg viewBox="0 0 24 24"><path d="M0 0 L24 24" stroke="#fff" fill="none"/></svg>';
  const out = sanitizeSvgIcon(raw);
  assert.equal(out.includes('viewBox'), true);
  assert.equal(out.includes('d="M0 0 L24 24"'), true);
  assert.equal(out.includes('stroke="#fff"'), true);
});

test('Kein SVG-Root -> leerer String (Fail-Closed)', () => {
  assert.equal(sanitizeSvgIcon('nur text'), '');
  assert.equal(sanitizeSvgIcon(null), '');
  assert.equal(sanitizeSvgIcon('<div onclick="x()">x</div>'), '');
  assert.equal(isSvgIcon('<svg onload=alert(1)>'), true);
  assert.equal(isSvgIcon('👤'), false);
});
