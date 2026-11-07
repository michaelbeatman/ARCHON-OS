import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

const DATA_FILE = path.resolve(process.cwd(), '../data/crm_theme_live_overrides.json');
const CSS_FILE = path.resolve(process.cwd(), 'src/app/custom_studio.css');

export async function GET() {
  try {
    if (fs.existsSync(DATA_FILE)) {
      const raw = fs.readFileSync(DATA_FILE, 'utf-8');
      return NextResponse.json(JSON.parse(raw));
    }
    return NextResponse.json({ rules: {}, rawCss: '', textOverrides: {} });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { rules, rawCss, textOverrides } = body || {};

    const payload = {
      rules: rules || {},
      textOverrides: textOverrides || {},
      rawCss: rawCss || ''
    };

    const dataDir = path.dirname(DATA_FILE);
    if (!fs.existsSync(dataDir)) {
      fs.mkdirSync(dataDir, { recursive: true });
    }
    fs.writeFileSync(DATA_FILE, JSON.stringify(payload, null, 2), 'utf-8');

    let cssText = '/* Archon CRM CSS Live Studio */\n';
    cssText += '#archon-css-studio, #archon-css-studio-minimized, #archon-css-highlighter { z-index: 99999999 !important; }\n\n';
    if (rawCss && rawCss.trim()) {
      cssText += rawCss + '\n';
    }
    if (rules && Object.keys(rules).length > 0) {
      Object.entries(rules).forEach(([selector, decls]) => {
        if (typeof decls === 'object' && decls !== null && Object.keys(decls).length > 0) {
          cssText += `${selector} {\n`;
          Object.entries(decls).forEach(([prop, val]) => {
            cssText += `  ${prop}: ${val};\n`;
          });
          cssText += '}\n\n';
        }
      });
    }

    const cssDir = path.dirname(CSS_FILE);
    if (!fs.existsSync(cssDir)) {
      fs.mkdirSync(cssDir, { recursive: true });
    }
    fs.writeFileSync(CSS_FILE, cssText, 'utf-8');

    return NextResponse.json({ ok: true, payload });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function DELETE() {
  try {
    if (fs.existsSync(DATA_FILE)) {
      fs.unlinkSync(DATA_FILE);
    }
    if (fs.existsSync(CSS_FILE)) {
      fs.writeFileSync(CSS_FILE, '/* Archon CRM CSS Live Studio */\n', 'utf-8');
    }
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
