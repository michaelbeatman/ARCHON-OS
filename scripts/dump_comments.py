import zipfile
import xml.etree.ElementTree as ET
import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

docx_path = r'.\docs\system\ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx'
z = zipfile.ZipFile(docx_path)
xml_data = z.read('word/comments.xml')
root = ET.fromstring(xml_data)

doc_xml = z.read('word/document.xml').decode('utf-8')

ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
for c in root.findall('.//w:comment', ns):
    cid = c.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
    author = c.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}author')
    date = c.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}date')
    text = ''.join(c.itertext()).strip()
    
    # find where in doc_xml this comment is anchored
    m = re.search(r'w:id=["\']' + cid + r'["\']', doc_xml)
    snippet = ''
    if m:
        pos = m.start()
        raw_snip = doc_xml[max(0, pos - 200):min(len(doc_xml), pos + 300)]
        snippet = re.sub(r'<[^>]+>', ' ', raw_snip).strip()
        snippet = ' '.join(snippet.split())
        
    print(f"=== COMMENT #{cid} ===")
    print(f"Author: {author} ({date})")
    print(f"Comment text: {text}")
    print(f"Anchored around: {snippet[:140]}...\n")
