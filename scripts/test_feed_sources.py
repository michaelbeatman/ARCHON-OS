import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

targets = [
    ('Handelsblatt Top', 'rss', 'https://www.handelsblatt.com/contentexport/feed/top-themen'),
    ('Handelsblatt Politik', 'rss', 'https://www.handelsblatt.com/contentexport/feed/politik'),
    ('Heise Online', 'rss', 'https://www.heise.de/rss/heise-atom.xml'),
    ('TechCrunch', 'rss', 'https://techcrunch.com/feed/'),
    ('ArXiv AI', 'rss', 'https://rss.arxiv.org/rss/cs.AI'),
    ('Tagesschau', 'rss', 'https://www.tagesschau.de/xml/rss2/'),
    ('Spektrum Search', 'search_feed', 'site:spektrum.de'),
    ('Bundesregierung Search', 'search_feed', 'site:bundesregierung.de ("Invest in Germany" OR Investitionsgipfel OR Wirtschaftspolitik)'),
    ('BMWK Search', 'search_feed', 'BMWK OR "Wirtschaftsministerium" (Investition OR Förderung OR Industrie)'),
    ('DIHK Search', 'search_feed', 'site:dihk.de (Außenwirtschaft OR Handelsabkommen OR Freihandelsabkommen)'),
    ('GTAI Search', 'search_feed', 'site:gtai.de OR "Germany Trade and Invest"'),
    ('Invest Summit Search', 'search_feed', '("Invest in Germany" OR "Investitionsgipfel" OR "Deutschlandfonds") Deutschland'),
    ('Bundesbank Search', 'search_feed', 'site:bundesbank.de (Pressemitteilung OR Monatsbericht OR Konjunktur)'),
    ('Reuters Business Search', 'search_feed', 'Reuters (Wirtschaft OR Börse OR Konjunktur OR Notenbank)'),
    ('Finanzen & Börse Search', 'search_feed', '(site:finanzen.net OR site:boerse-online.de) (Investition OR DAX OR Zinsen)')
]

for name, t_type, query_or_url in targets:
    url = f'https://news.google.com/rss/search?q={urllib.parse.quote(query_or_url)}&hl=de&gl=DE&ceid=DE:de' if t_type == 'search_feed' else query_or_url
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
            items = root.findall('.//item')
            if not items:
                items = root.findall('.//{http://www.w3.org/2005/Atom}entry')
            print(f'[OK] {name:<26}: {len(items)} Items geladen')
    except Exception as e:
        print(f'[FAIL] {name:<26}: {e}')
