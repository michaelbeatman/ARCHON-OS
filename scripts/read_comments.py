import zipfile, re, sys

sys.stdout.reconfigure(encoding='utf-8')

z = zipfile.ZipFile(r'.\docs\system\ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx')
doc_xml = z.read('word/document.xml').decode('utf-8')

pattern = re.compile(r'w:id=["\']8["\']')
for m in pattern.finditer(doc_xml):
    pos = m.start()
    snippet = doc_xml[max(0, pos - 300):pos + 600]
    print("Match at", pos)
    print(re.sub(r'<[^>]+>', ' ', snippet))
    print("=" * 60)
