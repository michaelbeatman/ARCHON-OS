import re
import sys
import docx
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

sys.stdout.reconfigure(encoding='utf-8')

COLOR_DARK = RGBColor(0x0F, 0x17, 0x2A)   # #0F172A Slate-900
COLOR_BODY = RGBColor(0x33, 0x41, 0x55)   # #334155 Slate-700
COLOR_TEAL = RGBColor(0x0E, 0x74, 0x90)   # #0E7490 Cyan/Teal
COLOR_MUTED = RGBColor(0x64, 0x74, 0x8B)  # #64748B Slate-500

def set_run_font(run, name=None, size_pt=None, bold=None, italic=None, color=None):
    if name:
        run.font.name = name
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color

def set_para_spacing(p, space_before_pt=None, space_after_pt=None, line_spacing=None, align=None):
    pf = p.paragraph_format
    if space_before_pt is not None:
        pf.space_before = Pt(space_before_pt)
    if space_after_pt is not None:
        pf.space_after = Pt(space_after_pt)
    if line_spacing is not None:
        pf.line_spacing = line_spacing
    if align is not None:
        p.alignment = align

def process_document(docx_path, out_path):
    doc = docx.Document(docx_path)
    
    print(f"Loaded {docx_path} with {len(doc.paragraphs)} paragraphs.")
    
    # We will iterate through paragraphs. Because we may need to split paragraphs,
    # let's look at paragraph indexes and text.
    # Note: Inserting paragraphs before p is supported via p.insert_paragraph_before().
    
    # Let's collect items to transform
    # 1. Split 'Kernkonzept & Architektur:\n...' where it occurs in one paragraph
    for p in list(doc.paragraphs):
        t = p.text.strip()
        if t.startswith('Kernkonzept & Architektur:\n') or t.startswith('Kernkonzept & Architektur: \n'):
            parts = t.split('\n', 1)
            header_txt = 'Kernkonzept & Architektur:'
            body_txt = parts[1].strip()
            
            # Insert header paragraph before p
            p_hdr = p.insert_paragraph_before()
            p_hdr.style = 'Normal'
            set_para_spacing(p_hdr, space_before_pt=6.0, space_after_pt=4.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r_hdr = p_hdr.add_run(header_txt)
            set_run_font(r_hdr, size_pt=9.5, bold=True, color=COLOR_DARK)
            
            # Now change p to be the body paragraph
            p.text = ''
            set_para_spacing(p, space_before_pt=4.0, space_after_pt=6.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r_body = p.add_run(body_txt)
            set_run_font(r_body, size_pt=10.0, color=COLOR_BODY)

    # 2. Split 'Ausgangslage & Zielsetzung:\n...' in Use Cases
    for p in list(doc.paragraphs):
        t = p.text.strip()
        if t.startswith('Ausgangslage & Zielsetzung:\n') or t.startswith('Ausgangslage & Zielsetzung: \n'):
            parts = t.split('\n', 1)
            header_txt = 'Ausgangslage & Zielsetzung:'
            body_txt = parts[1].strip()
            
            p_hdr = p.insert_paragraph_before()
            p_hdr.style = 'Normal'
            set_para_spacing(p_hdr, space_before_pt=6.0, space_after_pt=4.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r_hdr = p_hdr.add_run(header_txt)
            set_run_font(r_hdr, size_pt=9.5, bold=True, color=COLOR_DARK)
            
            p.text = ''
            set_para_spacing(p, space_before_pt=4.0, space_after_pt=6.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r_body = p.add_run(body_txt)
            set_run_font(r_body, size_pt=10.0, color=COLOR_BODY)

    # 3. Split single-line 'Arbeitsablauf: 1. ... ➔ 2. ...' into header + numbered paragraphs
    for p in list(doc.paragraphs):
        t = p.text.strip()
        if t.startswith('Arbeitsablauf: 1.') or t.startswith('Arbeitsablauf:  1.') or (t.startswith('Arbeitsablauf:') and '➔' in t):
            rest = t[len('Arbeitsablauf:'):].strip()
            # Split by arrow or numbers
            steps = re.split(r'\s*[➔➔]\s*|\s*(?=\d+\.\s+)', rest)
            steps = [s.strip() for s in steps if s.strip()]
            
            # Header
            p_hdr = p.insert_paragraph_before()
            p_hdr.style = 'Normal'
            set_para_spacing(p_hdr, space_before_pt=2.0, space_after_pt=2.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r_hdr = p_hdr.add_run('Arbeitsablauf: ')
            set_run_font(r_hdr, size_pt=9.0, bold=True, color=COLOR_DARK)
            
            # For each step except last, insert before p
            for step in steps[:-1]:
                p_step = p.insert_paragraph_before()
                p_step.style = 'Normal'
                set_para_spacing(p_step, space_before_pt=2.0, space_after_pt=2.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
                r_step = p_step.add_run(step)
                set_run_font(r_step, size_pt=9.0, color=COLOR_BODY)
                
            # Last step modifies p
            if steps:
                p.text = ''
                set_para_spacing(p, space_before_pt=2.0, space_after_pt=2.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
                r_last = p.add_run(steps[-1])
                set_run_font(r_last, size_pt=9.0, color=COLOR_BODY)

    # 4. Now process all paragraphs from 5.1 onwards to harmonize bullet points, praxistipps, etc.
    in_target_zone = False
    
    for i, p in enumerate(doc.paragraphs):
        t = p.text.strip()
        if '5.1 Modell-Wechsel' in t:
            in_target_zone = True
            
        if not in_target_zone:
            continue
            
        # Clean double bullets in List Bullet
        if p.style.name == 'List Bullet' and (t.startswith('•') or t.startswith('-')):
            # Strip bullet symbol
            cleaned = re.sub(r'^[•\-\*]\s*', '', t).strip()
            # Split into Key: Value if colon exists
            if ':' in cleaned:
                colon_idx = cleaned.find(':')
                key = cleaned[:colon_idx+1] + ' '
                val = cleaned[colon_idx+1:].strip()
                p.text = ''
                set_para_spacing(p, space_before_pt=1.0, space_after_pt=2.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
                r1 = p.add_run(key)
                set_run_font(r1, size_pt=9.0, bold=True, color=COLOR_DARK)
                r2 = p.add_run(val)
                set_run_font(r2, size_pt=9.0, bold=False, color=COLOR_BODY)
            else:
                p.text = ''
                set_para_spacing(p, space_before_pt=1.0, space_after_pt=2.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
                r = p.add_run(cleaned)
                set_run_font(r, size_pt=9.0, color=COLOR_BODY)
                
        # Format Praxistipp in sub-sections (e.g. Praxistipp: ...)
        elif t.startswith('Praxistipp:') and not t.startswith('Praxistipp & Leitplanke'):
            body_txt = t[len('Praxistipp:'):].strip()
            p.text = ''
            set_para_spacing(p, space_before_pt=2.0, space_after_pt=4.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r_label = p.add_run('Praxistipp: ')
            set_run_font(r_label, size_pt=9.0, bold=True, color=COLOR_TEAL)
            r_val = p.add_run(body_txt)
            set_run_font(r_val, size_pt=9.0, color=COLOR_BODY)
            
        # Format 💡 Praxistipp & Leitplanke: ...
        elif 'Praxistipp & Leitplanke:' in t:
            clean_txt = t
            p.text = ''
            set_para_spacing(p, space_before_pt=6.0, space_after_pt=6.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r_emoji = p.add_run('💡 ')
            set_run_font(r_emoji, name='Segoe UI Emoji', size_pt=9.5, bold=True, color=COLOR_TEAL)
            r_hdr = p.add_run('Praxistipp & Leitplanke: ')
            set_run_font(r_hdr, size_pt=9.5, bold=True, color=COLOR_TEAL)
            # Find the actual text after 'Praxistipp & Leitplanke:'
            idx = clean_txt.find('Praxistipp & Leitplanke:')
            val = clean_txt[idx + len('Praxistipp & Leitplanke:'):].strip()
            r_val = p.add_run(val)
            set_run_font(r_val, size_pt=9.5, color=COLOR_BODY)
            
        # Format Praxis-Workflow (Schritt für Schritt):
        elif t.startswith('Praxis-Workflow (Schritt für Schritt):') or t.startswith('Ablauf im System (Schritt für Schritt):'):
            p.text = ''
            set_para_spacing(p, space_before_pt=8.0, space_after_pt=4.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r = p.add_run(t)
            set_run_font(r, size_pt=9.5, bold=True, color=COLOR_DARK)
            
        # Format numbered steps under Praxis-Workflow or Use Case (1. ... to 9. ...)
        elif re.match(r'^\d+\.\s+', t) and p.style.name in ['Normal', 'List Paragraph'] and not t.startswith('Arbeitsablauf:'):
            set_para_spacing(p, space_before_pt=1.0, space_after_pt=3.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            # Format runs to 9.5pt body color
            for r in p.runs:
                set_run_font(r, size_pt=9.5, color=COLOR_BODY)
                
        # Format Komplexitätsstufe in Use Cases: ⚡ Komplexitätsstufe ...
        elif t.startswith('⚡ Komplexitätsstufe'):
            p.text = ''
            set_para_spacing(p, space_before_pt=2.0, space_after_pt=4.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r = p.add_run(t)
            set_run_font(r, size_pt=9.5, bold=True, color=COLOR_TEAL)
            
        # Format Beteiligte System-Module in Use Cases:
        elif t.startswith('Beteiligte System-Module:'):
            val = t[len('Beteiligte System-Module:'):].strip()
            p.text = ''
            set_para_spacing(p, space_before_pt=6.0, space_after_pt=6.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            r_hdr = p.add_run('Beteiligte System-Module: ')
            set_run_font(r_hdr, size_pt=9.5, bold=True, color=COLOR_DARK)
            # Split by arrow
            parts = re.split(r'(\s*[➔➔]\s*)', val)
            for part in parts:
                if '➔' in part or '➔' in part:
                    r_arrow = p.add_run(' ➔ ')
                    set_run_font(r_arrow, name='Segoe UI Symbol', size_pt=9.5, color=COLOR_TEAL)
                elif part.strip():
                    r_mod = p.add_run(part.strip())
                    set_run_font(r_mod, size_pt=9.5, color=COLOR_TEAL)

        # Format Heading 1
        elif p.style.name == 'Heading 1':
            set_para_spacing(p, space_before_pt=14.0, space_after_pt=2.0)
            for r in p.runs:
                set_run_font(r, color=COLOR_DARK)
                
        # Format Subtitle directly under Heading 1
        elif i > 0 and doc.paragraphs[i-1].style.name == 'Heading 1' and p.style.name == 'Normal' and t and not any('drawing' in r._r.xml for r in p.runs):
            set_para_spacing(p, space_before_pt=None, space_after_pt=2.0, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            for r in p.runs:
                set_run_font(r, size_pt=10.5, italic=True, color=COLOR_TEAL)

    # Save to output path
    doc.save(out_path)
    print(f"Successfully processed and saved to {out_path}.")

if __name__ == '__main__':
    src = r'C:\.Antigravity-projekte\AgenticOS-2026\docs\system\ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx'
    dst = r'C:\.Antigravity-projekte\AgenticOS-2026\docs\system\ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage_TEST.docx'
    process_document(src, dst)
