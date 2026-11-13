import http.server
import socketserver
import webbrowser
import urllib.parse
import os
import sys

PORT = 8555
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')

HTML_PAGE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Agentic OS - Initial Setup</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>body { background-color: #09090b; color: #f4f4f5; }</style>
</head>
<body class="min-h-screen flex items-center justify-center p-4">
    <div class="max-w-md w-full bg-zinc-900 border border-zinc-800 rounded-xl shadow-2xl p-6">
        <h1 class="text-2xl font-bold text-white mb-2">Agentic OS Setup</h1>
        <p class="text-zinc-400 text-sm mb-6">Bitte hinterlege deine API-Schlssel, um die lokalen KI-Agenten zu aktivieren. Diese Daten bleiben zu 100% lokal auf deinem Rechner.</p>
        
        <form method="POST" action="/save" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold text-zinc-300 mb-1">OpenRouter API Key (Empfohlen)</label>
                <input type="password" name="openrouter_key" class="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-indigo-500 focus:outline-none" placeholder="sk-or-v1-...">
            </div>
            <div>
                <label class="block text-xs font-semibold text-zinc-300 mb-1">Google Gemini API Key (Optional)</label>
                <input type="password" name="gemini_key" class="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-indigo-500 focus:outline-none" placeholder="AIza...">
            </div>
            <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-2 px-4 rounded mt-4 transition">
                Speichern & Setup abschlieen
            </button>
        </form>
    </div>
</body>
</html>
"""

HTML_SUCCESS = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Erfolg</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>body { background-color: #09090b; color: #f4f4f5; }</style>
</head>
<body class="min-h-screen flex items-center justify-center p-4">
    <div class="max-w-md w-full bg-zinc-900 border border-zinc-800 rounded-xl shadow-2xl p-6 text-center">
        <h1 class="text-2xl font-bold text-emerald-500 mb-2">✓ Gespeichert</h1>
        <p class="text-zinc-400 text-sm mb-4">Deine Keys wurden sicher hinterlegt. Du kannst dieses Fenster nun schlieen.</p>
        <p class="text-xs text-zinc-500">Dein KI-Agent (Codex/Claude) kann nun den Boot-Prozess fortsetzen.</p>
    </div>
</body>
</html>
"""

class SetupHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode('utf-8'))

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = urllib.parse.parse_qs(post_data)
        
        openrouter = data.get('openrouter_key', [''])[0].strip()
        gemini = data.get('gemini_key', [''])[0].strip()
        
        with open(ENV_PATH, 'w', encoding='utf-8') as f:
            if openrouter: f.write(f"OPENROUTER_API_KEY={openrouter}\n")
            if gemini: f.write(f"GEMINI_API_KEY={gemini}\n")
            
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML_SUCCESS.encode('utf-8'))
        
        print("\n[+] API Keys erfolgreich gespeichert.")
        print("[+] Setup-Server wird beendet...")
        # Shut down in a separate thread so the response completes
        import threading
        threading.Thread(target=self.server.shutdown, daemon=True).start()

if __name__ == "__main__":
    print(f"Starte Setup Wizard auf http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    with socketserver.TCPServer(("", PORT), SetupHandler) as httpd:
        httpd.serve_forever()
    print("Setup abgeschlossen. Gebe Kontrolle an Agenten zurck.")
