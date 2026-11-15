#!/usr/bin/env node
/**
 * Kompilier-Skript für vorkompiliertes Archon-OS Tailwind CSS (`/static/css/tailwind.generated.css`).
 * Nutzt die lokal vorhandene Tailwind-v3.4/PostCSS-Engine (`static/js/tailwind.cdn.js`) offline
 * in Node.js, scannt alle HTML- und JS-Dateien unter `static/` und ersetzt damit den teuren
 * Runtime-CSS-Compiler im Browser.
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");
const STATIC_DIR = path.join(REPO_ROOT, "static");
const TAILWIND_BUNDLE = path.join(STATIC_DIR, "js", "tailwind.cdn.js");
const OUTPUT_CSS = path.join(STATIC_DIR, "css", "tailwind.generated.css");

const EXCLUDE_DIRS = new Set(["vendor", "hermes-webui", "locales", "avatars"]);
const TOKEN_REGEX =
  /(?:!?[a-zA-Z0-9_-]+:)*-?[a-zA-Z0-9_.-]+(?:\[[^\s"'`<>{}\]]+\])?(?:\/[a-zA-Z0-9_.\[\]%]+)?/g;

const SAFELIST_CLASSES = [
  "bg-emerald-500", "bg-amber-500", "bg-rose-500", "bg-sky-500", "bg-indigo-500",
  "bg-blue-500", "bg-slate-400", "bg-red-500", "bg-purple-500", "bg-cyan-500",
  "text-emerald-500", "text-amber-500", "text-rose-500", "text-sky-500", "text-indigo-500",
  "border-emerald-500", "border-amber-500", "border-rose-500", "border-sky-500", "border-indigo-500",
  "ring-1", "ring-2", "ring-indigo-500/30", "ring-emerald-500/30", "ring-amber-500/30", "ring-rose-500/30",
  "animate-pulse", "animate-ping", "animate-spin", "hidden", "flex", "grid", "block", "inline-flex",
  "dark", "light",
];

function collectFiles(dir, results = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (EXCLUDE_DIRS.has(entry.name)) continue;
      collectFiles(full, results);
    } else if (entry.isFile()) {
      if (full === TAILWIND_BUNDLE) continue;
      if (entry.name.endsWith(".html") || entry.name.endsWith(".js")) {
        results.push(full);
      }
    }
  }
  return results;
}

function extractTokens(files) {
  const tokens = new Set(SAFELIST_CLASSES);
  for (const file of files) {
    const content = fs.readFileSync(file, "utf8");
    const classAttrs = content.matchAll(/class(?:Name)?\s*=\s*["'`]([^"'`]+)["'`]/g);
    for (const m of classAttrs) {
      for (const part of m[1].split(/\s+/)) {
        if (part && !part.includes("${")) tokens.add(part);
      }
    }
    const matches = content.match(TOKEN_REGEX) || [];
    for (const tok of matches) {
      // Nur plausible Tailwind-Utilities (muss "-" oder ":" oder bekanntes Einzelwort enthalten)
      if (tok.length >= 2 && tok.length <= 80 && (tok.includes("-") || tok.includes(":") || tok.startsWith("!"))) {
        tokens.add(tok);
      }
    }
  }
  return Array.from(tokens);
}

async function compileCss(tokens) {
  const bundleCode = fs.readFileSync(TAILWIND_BUNDLE, "utf8");
  const classListArray = tokens;
  let capturedStyle = "";
  let observerCb = null;
  let styleUpdates = 0;

  const headNode = {
    append(el) {
      if (el && typeof el.textContent === "string" && el.textContent.length > capturedStyle.length) {
        capturedStyle = el.textContent;
      }
    },
  };

  const sandbox = {
    console: { log: () => {}, warn: () => {}, error: console.error },
    setTimeout,
    clearTimeout,
    Promise,
    Set,
    Map,
    Array,
    Object,
    Proxy,
    Symbol,
    TypeError,
    Error,
    RegExp,
    JSON,
    Math,
    Number,
    String,
    Boolean,
    Uint8Array,
    Date,
    MutationObserver: class {
      constructor(cb) {
        observerCb = cb;
      }
      observe() {}
      disconnect() {}
    },
    document: {
      documentElement: {},
      body: {},
      head: headNode,
      querySelectorAll(sel) {
        if (sel === "[class]") {
          return [{ classList: classListArray }];
        }
        return [];
      },
      createElement(tag) {
        let _text = "";
        return {
          tagName: tag.toUpperCase(),
          isConnected: true,
          get textContent() {
            return _text;
          },
          set textContent(v) {
            _text = String(v || "");
            capturedStyle = _text;
            styleUpdates++;
          },
        };
      },
    },
  };
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;

  vm.runInNewContext(bundleCode, sandbox, { filename: "tailwind.cdn.js" });

  // Zuerst alle statischen Klassen einspeisen, bevor MutationObserver/config läuft,
  // oder direkt `config` setzen und auf den Abschluss der async PostCSS-Pipeline warten.
  sandbox.tailwind.config = {
    darkMode: "class",
    theme: {
      extend: {
        fontFamily: {
          sans: ["Outfit", "Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "sans-serif"],
          outfit: ["Outfit", "sans-serif"],
          mono: ["JetBrains Mono", "monospace"],
          julius: ["Julius Sans One", "sans-serif"],
        },
        colors: {
          border: "var(--border)",
          input: "var(--input)",
          ring: "var(--ring)",
          background: "var(--background)",
          foreground: "var(--foreground)",
          primary: { DEFAULT: "var(--primary)", foreground: "var(--primary-foreground)" },
          secondary: { DEFAULT: "var(--secondary)", foreground: "var(--secondary-foreground)" },
          destructive: { DEFAULT: "var(--destructive)", foreground: "var(--destructive-foreground)" },
          muted: { DEFAULT: "var(--muted)", foreground: "var(--muted-foreground)" },
          accent: { DEFAULT: "var(--accent-shadcn)", foreground: "var(--accent-shadcn-foreground)" },
          card: { DEFAULT: "var(--card)", foreground: "var(--card-foreground)" },
        },
      },
    },
  };

  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 100));
    if (styleUpdates > 0 && capturedStyle.includes(".hidden")) break;
  }

  if (!capturedStyle || !capturedStyle.includes(".hidden")) {
    if (typeof observerCb === "function") {
      await observerCb([]);
    }
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 100));
      if (capturedStyle.includes(".hidden")) break;
    }
  }

  if (!capturedStyle || !capturedStyle.includes(".hidden")) {
    throw new Error(`Tailwind build incomplete (${capturedStyle.length} bytes, updates=${styleUpdates})`);
  }

  fs.mkdirSync(path.dirname(OUTPUT_CSS), { recursive: true });
  const header = `/* Auto-generated by scripts/build_tailwind_css.mjs — precompiled Tailwind v3.4 utilities & preflight */\n`;
  fs.writeFileSync(OUTPUT_CSS, header + capturedStyle, "utf8");
  return { outputPath: OUTPUT_CSS, bytes: Buffer.byteLength(header + capturedStyle, "utf8"), tokenCount: tokens.length };
}

const files = collectFiles(STATIC_DIR);
const tokens = extractTokens(files);
const result = await compileCss(tokens);
console.log(`[build_tailwind_css] Scanned ${files.length} files, ${result.tokenCount} tokens -> ${result.outputPath} (${result.bytes} bytes)`);
