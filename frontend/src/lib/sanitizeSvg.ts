/**
 * F-068 / F-069 — gemeinsame SSOT für Icon-Strings aus localStorage.
 *
 * Die Icons in CRM-Kanban und DesignEditor werden per `dangerouslySetInnerHTML`
 * gerendert. Die bisherige Prüfung erkannte nur das Vorhandensein von `<svg`,
 * liess aber Event-Handler und gefährliche Attribute/URLs ungefiltert durch.
 *
 * Dieser Sanitizer arbeitet ohne zusätzliche Dependency und ohne DOM
 * (funktioniert daher auch bei SSR): Strict-Whitelist für Elemente und
 * Attribute, alle `on*`-Attribute sowie gefährliche Tags/URLs werden entfernt.
 * Output ist ausschliesslich wohlgeformtes, inertes SVG-Markup.
 */

/** Erlaubte SVG-Elemente: lowercase -> kanonischer (case-sensitiver) Name. */
const ALLOWED_TAGS: Record<string, string> = {
  svg: 'svg',
  g: 'g',
  path: 'path',
  circle: 'circle',
  ellipse: 'ellipse',
  rect: 'rect',
  line: 'line',
  polyline: 'polyline',
  polygon: 'polygon',
  defs: 'defs',
  title: 'title',
  desc: 'desc',
  symbol: 'symbol',
  use: 'use',
  lineargradient: 'linearGradient',
  radialgradient: 'radialGradient',
  stop: 'stop',
  clippath: 'clipPath',
  mask: 'mask',
  pattern: 'pattern',
  text: 'text',
  tspan: 'tspan',
};

/** Erlaubte Attribute: lowercase -> kanonischer SVG-Name. `on*` ist nie dabei. */
const ALLOWED_ATTRS: Record<string, string> = {
  xmlns: 'xmlns',
  'xmlns:xlink': 'xmlns:xlink',
  version: 'version',
  viewbox: 'viewBox',
  width: 'width',
  height: 'height',
  x: 'x',
  y: 'y',
  x1: 'x1',
  y1: 'y1',
  x2: 'x2',
  y2: 'y2',
  cx: 'cx',
  cy: 'cy',
  r: 'r',
  rx: 'rx',
  ry: 'ry',
  d: 'd',
  points: 'points',
  fill: 'fill',
  'fill-opacity': 'fill-opacity',
  'fill-rule': 'fill-rule',
  stroke: 'stroke',
  'stroke-width': 'stroke-width',
  'stroke-linecap': 'stroke-linecap',
  'stroke-linejoin': 'stroke-linejoin',
  'stroke-dasharray': 'stroke-dasharray',
  'stroke-dashoffset': 'stroke-dashoffset',
  'stroke-opacity': 'stroke-opacity',
  'stroke-miterlimit': 'stroke-miterlimit',
  opacity: 'opacity',
  transform: 'transform',
  class: 'class',
  id: 'id',
  offset: 'offset',
  'stop-color': 'stop-color',
  'stop-opacity': 'stop-opacity',
  gradientunits: 'gradientUnits',
  gradienttransform: 'gradientTransform',
  'clip-path': 'clip-path',
  mask: 'mask',
  preserveaspectratio: 'preserveAspectRatio',
  'aria-hidden': 'aria-hidden',
  focusable: 'focusable',
  display: 'display',
};

/** Attribute, die grundsätzlich gefährlich sind (CSS/URL-/Formular-Vektoren). */
const FORBIDDEN_ATTRS = new Set([
  'style', 'srcdoc', 'formaction', 'action', 'background', 'poster',
  'ping', 'srcset', 'integrity', 'nonce',
]);

const SAFE_FRAGMENT_URL = /url\(\s*['"]?#[A-Za-z0-9_.:-]+['"]?\s*\)/gi;
const FRAGMENT_ONLY = /^#[A-Za-z0-9_.:-]+$/;

function escapeText(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeAttr(value: string): string {
  return escapeText(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Lehnt Skript-/Daten-URLs, CSS-Injektion und Fremd-`url(...)` ab. */
function isSafeValue(value: string): boolean {
  if (/[<>\u0000-\u001f]/.test(value)) return false;
  if (/(javascript|vbscript|data)\s*:/i.test(value)) return false;
  if (/expression\s*\(/i.test(value)) return false;
  if (/@import/i.test(value)) return false;
  if (/url\s*\(/i.test(value) && /url\s*\(/i.test(value.replace(SAFE_FRAGMENT_URL, ''))) {
    return false;
  }
  return true;
}

function sanitizeAttributes(raw: string): string {
  let result = '';
  const attrRe = /([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
  let match: RegExpExecArray | null;

  while ((match = attrRe.exec(raw)) !== null) {
    const name = match[1].toLowerCase();
    // Event-Handler (onload, onclick, onmouseover, …) konsequent entfernen.
    if (name.startsWith('on') || FORBIDDEN_ATTRS.has(name)) continue;

    const value = match[2] ?? match[3] ?? match[4] ?? '';

    // href/xlink:href nur als interne Fragment-Referenz (z. B. <use href="#id">).
    if (name === 'href' || name === 'xlink:href') {
      if (FRAGMENT_ONLY.test(value.trim())) {
        result += ` ${name}="${escapeAttr(value.trim())}"`;
      }
      continue;
    }

    const canonical = ALLOWED_ATTRS[name];
    if (!canonical || !isSafeValue(value)) continue;
    result += ` ${canonical}="${escapeAttr(value)}"`;
  }
  return result;
}

/** True, wenn der String ein SVG-Icon ist (mit oder ohne Leading-Whitespace). */
export function isSvgIcon(raw: unknown): boolean {
  return typeof raw === 'string' && /^<svg[\s>]/i.test(raw.trim());
}

/**
 * Sanitiert einen Icon-String zu inertem SVG. Bei jedem verdächtigen Konstrukt wird das
 * betroffene Element/Attribut verworfen; ist kein `<svg>`-Root erkennbar, wird
 * der leere String zurückgegeben (Fail-Closed).
 */
export function sanitizeSvgIcon(raw: unknown): string {
  if (typeof raw !== 'string' || !isSvgIcon(raw)) return '';

  const source = raw.trim();
  const tokenRe = /<!--[\s\S]*?-->|<!DOCTYPE[^>]*>|<\?[\s\S]*?\?>|<(\/?)\s*([A-Za-z][A-Za-z0-9:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>|([^<]+)/g;
  const openTags: string[] = [];
  let result = '';
  let match: RegExpExecArray | null;

  while ((match = tokenRe.exec(source)) !== null) {
    // Klartext zwischen Tags: immer escapen.
    if (match[5] !== undefined) {
      result += escapeText(match[5]);
      continue;
    }
    // Kommentare, DOCTYPE und Processing Instructions komplett verwerfen.
    if (match[2] === undefined) continue;

    const closing = match[1] === '/';
    const canonical = ALLOWED_TAGS[match[2].toLowerCase()];
    if (!canonical) continue; // z. B. script, foreignObject, iframe, object, … → raus

    if (closing) {
      if (openTags[openTags.length - 1] === canonical) {
        result += `</${canonical}>`;
        openTags.pop();
      }
      continue;
    }

    const attributes = match[3] ?? '';
    const selfClosing = /\/\s*$/.test(attributes);
    result += `<${canonical}${sanitizeAttributes(attributes)}${selfClosing ? ' /' : ''}>`;
    if (!selfClosing) openTags.push(canonical);
  }

  while (openTags.length) result += `</${openTags.pop()}>`;

  return isSvgIcon(result) ? result : '';
}
