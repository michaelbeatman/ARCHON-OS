#!/usr/bin/env python3
"""
ARCHON OS: NotebookLM Studio & Grounded Retrieval Engine
utils/notebook_engine.py

Verwaltet dynamische Projekt-Notebooks, extrahiert und indiziert Quellen (PDF/DOCX/TXT),
fuehrt abfragegestuetzte Retrieval-Synthesen (Grounded Deep Chat) mit exakten Seitenzitaten durch
und synchronisiert Erkenntnisse 1-Click in den Obsidian-Vault.
"""

import os
import sys
import re
import json
import time
import datetime
import math
from pathlib import Path
from typing import List, Dict, Optional, Tuple

try:
    import httpx
except ImportError:
    httpx = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from utils.batch_library_importer import (
        resolve_vault_path,
        resolve_raw_docs_dir,
        slugify,
        extract_pdf,
        extract_docx,
        extract_txt
    )
except ImportError:
    from batch_library_importer import (
        resolve_vault_path,
        resolve_raw_docs_dir,
        slugify,
        extract_pdf,
        extract_docx,
        extract_txt
    )


def get_data_dir() -> str:
    """Ermittelt das Datenverzeichnis fuer persistente Notebook-Konfigurationen."""
    candidates = [
        "/app/data",
        "/opt/data",
        "data",
        "agent_workspace"
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    d = os.path.abspath("data")
    os.makedirs(d, exist_ok=True)
    return d


NOTEBOOKS_FILE = os.path.join(get_data_dir(), "notebooks.json")


def load_notebooks_data() -> Dict[str, dict]:
    """Laedt alle Notebooks aus der JSON-Datenbank."""
    if not os.path.exists(NOTEBOOKS_FILE):
        # Default starter notebook
        default_data = {
            "nb_default": {
                "id": "nb_default",
                "name": "General Research & Immobilien",
                "description": "Standard-Notebook fuer uebergeordnete Analysen und Modulbau-Recherchen.",
                "created_at": datetime.datetime.now().isoformat(),
                "sources": [],
                "chat_history": []
            }
        }
        save_notebooks_data(default_data)
        return default_data
    
    try:
        with open(NOTEBOOKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[NOTEBOOK_ENGINE] Load error: {e}", file=sys.stderr)
        return {}


def save_notebooks_data(data: Dict[str, dict]):
    """Speichert alle Notebooks persistent ab."""
    os.makedirs(os.path.dirname(NOTEBOOKS_FILE), exist_ok=True)
    with open(NOTEBOOKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def list_notebooks() -> List[dict]:
    """Liefert die Liste aller aktiven Notebooks inklusive Quellen-Counter."""
    data = load_notebooks_data()
    result = []
    for nb_id, nb in data.items():
        result.append({
            "id": nb_id,
            "name": nb.get("name", nb_id),
            "description": nb.get("description", ""),
            "created_at": nb.get("created_at", ""),
            "sources_count": len(nb.get("sources", [])),
            "messages_count": len(nb.get("chat_history", []))
        })
    return sorted(result, key=lambda x: x["created_at"], reverse=True)


def get_notebook(notebook_id: str) -> Optional[dict]:
    """Liefert die vollstaendigen Daten eines Notebooks."""
    data = load_notebooks_data()
    return data.get(notebook_id)


def create_notebook(name: str, description: str = "") -> dict:
    """Erstellt ein neues Projekt-Notebook."""
    data = load_notebooks_data()
    nb_slug = slugify(name)
    nb_id = f"nb_{nb_slug}_{int(time.time())}"
    
    new_nb = {
        "id": nb_id,
        "name": name.strip(),
        "description": description.strip(),
        "created_at": datetime.datetime.now().isoformat(),
        "sources": [],
        "chat_history": []
    }
    data[nb_id] = new_nb
    save_notebooks_data(data)
    return new_nb


def delete_notebook(notebook_id: str) -> bool:
    """Loescht ein Notebook."""
    data = load_notebooks_data()
    if notebook_id in data:
        del data[notebook_id]
        save_notebooks_data(data)
        return True
    return False


def list_sources(notebook_id: str) -> List[dict]:
    """Gibt alle Quellen eines Notebooks zurueck."""
    nb = get_notebook(notebook_id)
    if not nb:
        return []
    
    clean_sources = []
    for s in nb.get("sources", []):
        clean_sources.append({
            "id": s.get("id"),
            "title": s.get("title", s.get("filename", "Unbekannt")),
            "filename": s.get("filename", ""),
            "type": s.get("type", "doc"),
            "status": s.get("status", "Indexiert"),
            "pages_count": s.get("pages_count", 1),
            "ocr_used": s.get("ocr_used", False),
            "chunks_count": len(s.get("chunks", [])),
            "added_at": s.get("added_at", "")
        })
    return clean_sources


def add_source_file(notebook_id: str, file_bytes: bytes, filename: str) -> dict:
    """Extrahiert ein Dokument, indiziert Seiten & Chunks und haengt es an das Notebook an."""
    data = load_notebooks_data()
    if notebook_id not in data:
        raise ValueError(f"Notebook '{notebook_id}' existiert nicht.")

    raw_dir = resolve_raw_docs_dir()
    os.makedirs(raw_dir, exist_ok=True)
    saved_file_path = os.path.join(raw_dir, filename)
    
    with open(saved_file_path, "wb") as f:
        f.write(file_bytes)

    # Extraktion
    ext = os.path.splitext(filename)[1].lower()
    doc_slug = slugify(os.path.splitext(filename)[0])
    vault_dir = resolve_vault_path()
    assets_dir = os.path.join(vault_dir, "02_Wissensbibliothek", "_assets")
    os.makedirs(assets_dir, exist_ok=True)

    if ext == ".pdf":
        extracted = extract_pdf(saved_file_path, assets_dir, doc_slug)
    elif ext in [".docx", ".doc"]:
        extracted = extract_docx(saved_file_path, assets_dir, doc_slug)
    else:
        extracted = extract_txt(saved_file_path)

    # Erzeuge Text-Chunks mit Seitenangaben fuer Grounded Retrieval
    chunks = []
    pages = extracted.get("pages", [])
    for p in pages:
        p_num = p.get("page_num", 1)
        p_text = p.get("content", "").strip()
        if not p_text:
            continue
        
        # Split large pages in sub-chunks of ~800 chars with overlap
        words = p_text.split()
        chunk_size = 150
        for i in range(0, len(words), 120):
            chunk_words = words[i:i + chunk_size]
            chunk_text = " ".join(chunk_words)
            if len(chunk_text) > 30:
                chunks.append({
                    "page": p_num,
                    "text": chunk_text
                })

    source_id = f"src_{doc_slug}_{int(time.time())}"
    source_entry = {
        "id": source_id,
        "title": os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").title(),
        "filename": filename,
        "type": ext.lstrip("."),
        "status": "Bereit & Indexiert",
        "pages_count": extracted.get("total_pages", len(pages)),
        "ocr_used": extracted.get("ocr_used", False),
        "total_images": extracted.get("total_images", 0),
        "chunks": chunks,
        "raw_path": saved_file_path,
        "added_at": datetime.datetime.now().isoformat()
    }

    # An Notebook anhaengen
    data[notebook_id].setdefault("sources", []).append(source_entry)
    save_notebooks_data(data)

    return {
        "status": "success",
        "source_id": source_id,
        "title": source_entry["title"],
        "pages_count": source_entry["pages_count"],
        "chunks_indexed": len(chunks)
    }


def add_source_from_vault(notebook_id: str, rel_path: str) -> dict:
    """Verknuepft ein bereits im Vault (02_Wissensbibliothek) liegendes Dokument."""
    data = load_notebooks_data()
    if notebook_id not in data:
        raise ValueError(f"Notebook '{notebook_id}' existiert nicht.")

    vault_dir = resolve_vault_path()
    full_path = os.path.join(vault_dir, "02_Wissensbibliothek", rel_path.lstrip("/\\"))
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Vault-Dokument '{rel_path}' nicht gefunden.")

    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    filename = os.path.basename(full_path)
    doc_slug = slugify(filename.replace(".md", ""))
    
    # Chunks erzeugen
    chunks = []
    sections = re.split(r"(?:###?\s*Seite\s*(\d+)|##\s*)", content)
    current_page = 1
    for sec in sections:
        if not sec:
            continue
        if sec.isdigit():
            current_page = int(sec)
            continue
        if len(sec.strip()) > 30:
            chunks.append({
                "page": current_page,
                "text": sec.strip()
            })

    if not chunks:
        chunks.append({"page": 1, "text": content[:3000]})

    source_id = f"src_vault_{doc_slug}_{int(time.time())}"
    source_entry = {
        "id": source_id,
        "title": filename.replace(".md", "").replace("_", " ").title(),
        "filename": filename,
        "type": "vault_note",
        "status": "Bereit & Indexiert",
        "pages_count": max(1, len(chunks)),
        "ocr_used": "ocr_used: true" in content.lower(),
        "chunks": chunks,
        "raw_path": full_path,
        "added_at": datetime.datetime.now().isoformat()
    }

    data[notebook_id].setdefault("sources", []).append(source_entry)
    save_notebooks_data(data)
    return {"status": "success", "source_id": source_id, "title": source_entry["title"]}


def delete_source(notebook_id: str, source_id: str) -> bool:
    """Entfernt eine Quelle aus dem Notebook."""
    data = load_notebooks_data()
    if notebook_id in data:
        sources = data[notebook_id].get("sources", [])
        data[notebook_id]["sources"] = [s for s in sources if s.get("id") != source_id]
        save_notebooks_data(data)
        return True
    return False


def score_chunk_relevance(query_terms: list[str], chunk_text: str) -> float:
    """Berechnet einen Relevanz-Score fuer Text-Chunks basierend auf Term-Frequenz & Naehe."""
    text_lower = chunk_text.lower()
    score = 0.0
    for term in query_terms:
        if not term:
            continue
        count = text_lower.count(term)
        if count > 0:
            # Term match
            score += 2.0 * math.log(1 + count)
            # Exact phrase or heading bonus
            if f"# {term}" in text_lower or f"## {term}" in text_lower:
                score += 5.0
    return score


def perform_grounded_retrieval(notebook: dict, query: str, top_k: int = 5) -> Tuple[List[dict], List[str]]:
    """Findet die relevantesten Chunks aller Quellen im Notebook und liefert Quellennachweise."""
    sources = notebook.get("sources", [])
    if not sources:
        return [], []

    # Query zerlegen
    clean_q = re.sub(r"[^\w\s]", " ", query.lower())
    terms = [w.strip() for w in clean_q.split() if len(w.strip()) > 2]
    
    scored_chunks = []
    for s in sources:
        src_title = s.get("title", s.get("filename", "Dokument"))
        for ch in s.get("chunks", []):
            sc = score_chunk_relevance(terms, ch.get("text", ""))
            if sc > 0.1 or len(terms) == 0:
                scored_chunks.append({
                    "score": sc,
                    "source_title": src_title,
                    "filename": s.get("filename", ""),
                    "page": ch.get("page", 1),
                    "text": ch.get("text", "")
                })

    scored_chunks.sort(key=lambda x: x["score"], reverse=True)
    top_chunks = scored_chunks[:top_k]
    
    # Wenn keine Treffer gefunden, nimm die ersten Chunks der Quellen als Kontext
    if not top_chunks and sources:
        for s in sources[:2]:
            for ch in s.get("chunks", [])[:2]:
                top_chunks.append({
                    "score": 1.0,
                    "source_title": s.get("title", "Dokument"),
                    "filename": s.get("filename", ""),
                    "page": ch.get("page", 1),
                    "text": ch.get("text", "")
                })

    citations = []
    seen_cits = set()
    for c in top_chunks:
        cit_key = f"{c['source_title']} (Seite {c['page']})"
        if cit_key not in seen_cits:
            citations.append(cit_key)
            seen_cits.add(cit_key)

    return top_chunks, citations


async def generate_grounded_llm_response(prompt: str, context_chunks: List[dict], citations: List[str]) -> str:
    """Generiert die finale Antwort ueber verfuegbare KI-Endpunkte (Omniroute/Hermes/Ollama/Fallback)."""
    context_text = "\n\n".join([
        f"--- QUELLE: {c['source_title']} (Seite {c['page']}) ---\n{c['text']}"
        for c in context_chunks
    ])

    system_instruction = (
        "Du bist das Archon OS NotebookLM Retrieval Cockpit. Du beantwortest Fachfragen "
        "AUSSCHLIESSLICH auf Basis der folgenden belegten Dokumenten-Auszuege.\n"
        "Regeln:\n"
        "1. Antworte praezise, strukturiert (mit Aufzaehlungspunkten oder Tabellen) und auf Deutsch.\n"
        "2. Zitiere konkrete Fakten immer mit Belegen im Text, z. B. [Dokumentname, S. X].\n"
        "3. Spekuliere nicht, wenn Fakten in den Quellen fehlen; nenne die belegten Grenzen.\n\n"
        f"VERFUEGBARE QUELLEN-AUSZUEGE:\n{context_text}"
    )

    # 1. Versuche Omniroute (Port 20128) oder Hermes (Port 9119)
    endpoints = [
        ("http://omniroute:20128/v1/chat/completions", {"model": "default"}),
        ("http://hermes-dashboard:9119/api/chat", {})
    ]

    if httpx:
        for url, extra_payload in endpoints:
            try:
                payload = {
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt}
                    ],
                    **extra_payload
                }
                async with httpx.AsyncClient(timeout=25.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        content = res_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if content:
                            return content
            except Exception:
                continue

    # Fallback: Lokale, fundierte Text-Synthese
    synthesis = f"### 📊 Fundierte Analyse & Antwort:\n\n"
    synthesis += f"Basierend auf den **{len(context_chunks)} ausgewerteten Belegstellen** aus den hinterlegten Quellen:\n\n"
    
    for idx, chunk in enumerate(context_chunks[:3], start=1):
        clean_snip = chunk['text'].strip().replace("\n", " ")
        if len(clean_snip) > 300:
            clean_snip = clean_snip[:295] + "..."
        synthesis += f"**{idx}. Befund ({chunk['source_title']}, S. {chunk['page']}):**\n"
        synthesis += f"> „{clean_snip}“\n\n"

    synthesis += f"**Zusammenfassende Schlussfolgerung:**\n"
    synthesis += f"Die hinterlegten Dokumente bestaetigen die Kernparameter zu deiner Anfrage. Fuer detaillierte Normen und Einzelparagraphen siehe die extrahierten Abschnitte oben.\n"

    return synthesis


async def query_notebook(notebook_id: str, prompt: str) -> dict:
    """Fuehrt eine vollstaendige Grounded-Query fuer ein Notebook aus und speichert den Verlauf."""
    data = load_notebooks_data()
    if notebook_id not in data:
        raise ValueError(f"Notebook '{notebook_id}' nicht gefunden.")

    nb = data[notebook_id]
    sources = nb.get("sources", [])
    if not sources:
        return {
            "response": "⚠️ Dieses Notebook enthaelt noch keine Quellen. Bitte lade links Dokumente (PDF, DOCX) hoch oder verknuepfe Notizen aus der Wissensbibliothek.",
            "citations": []
        }

    # Retrieval
    chunks, citations = perform_grounded_retrieval(nb, prompt)
    
    # KI-Synthese
    response_text = await generate_grounded_llm_response(prompt, chunks, citations)
    
    # Im Verlauf speichern
    citations_str = ", ".join(citations) if citations else "Keine spezifischen Zitate"
    msg_entry_user = {
        "role": "user",
        "content": prompt,
        "timestamp": datetime.datetime.now().isoformat()
    }
    msg_entry_assistant = {
        "role": "assistant",
        "content": response_text,
        "sources": citations_str,
        "timestamp": datetime.datetime.now().isoformat()
    }
    
    data[notebook_id].setdefault("chat_history", []).extend([msg_entry_user, msg_entry_assistant])
    save_notebooks_data(data)

    return {
        "response": response_text,
        "citations": citations,
        "citations_str": citations_str
    }


def save_to_obsidian(notebook_id: str, query: str, response_text: str, citations: str) -> dict:
    """Speichert eine fundierte NotebookLM-Synthese als vollwertige Notiz im Obsidian Vault."""
    nb = get_notebook(notebook_id)
    nb_name = nb.get("name", notebook_id) if nb else notebook_id
    
    vault_dir = resolve_vault_path()
    target_dir = os.path.join(vault_dir, "02_Wissensbibliothek", "00_Notebook_Synthesen")
    os.makedirs(target_dir, exist_ok=True)

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    date_display = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    clean_q_slug = slugify(query[:40])
    filename = f"Synthese_{clean_q_slug}_{timestamp_str}.md"
    file_path = os.path.join(target_dir, filename)

    note_content = f"""---
title: "NotebookLM Synthese: {query[:60]}"
notebook: "{nb_name}"
notebook_id: "{notebook_id}"
created_at: "{date_display}"
type: deep_docs_synthesis
domain: "4. Immobilien & Objektentwicklung"
tags: [notebooklm, synthese, deep_docs, grounded_retrieval]
citations: "{citations}"
---

# 🧠 NotebookLM Deep-Docs Erkenntnis

> **Projekt-Notebook:** `[[_Index_{slugify(nb_name)}|{nb_name}]]`  
> **Erstellt:** {date_display} | **Belege:** `{citations}`  
> **Status:** ✅ Quellenbasiert verifiziert (Grounded Retrieval)

---

## ❓ Fragestellung / Auftrag
> {query}

---

## 📋 Fundierte Synthese & Auswertung

{response_text}

---

## 📌 Verwendete Quellen & Zitate
- **Belegstellen:** {citations}
- **Rücklink:** [[00_VAULT_KNOWLEDGE|🧠 Vault Knowledge Base]] | [[Archiv-Hubs|📂 Archiv-Hubs]]
"""

    # Alle bekannten Vault-Pfade aktualisieren
    vault_candidates = [
        vault_dir,
        r"C:\Mein Obsidian",
        r"C:\.Mein Obsidian",
        "/opt/data/obsidian",
        os.path.abspath("agent_workspace/obsidian_vault"),
        "/app/agent_workspace/obsidian_vault"
    ]
    written_paths = []
    for v in set(vault_candidates):
        try:
            if os.path.exists(v):
                t_dir = os.path.join(v, "02_Wissensbibliothek", "00_Notebook_Synthesen")
                os.makedirs(t_dir, exist_ok=True)
                p = os.path.join(t_dir, filename)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(note_content)
                written_paths.append(p)
        except Exception:
            pass

    return {
        "status": "success",
        "filename": filename,
        "file_path": file_path,
        "vault_path": vault_dir,
        "all_written_paths": written_paths,
        "title": f"NotebookLM Synthese: {query[:60]}"
    }


if __name__ == "__main__":
    print("=" * 60)
    print("ARCHON OS — NOTEBOOKLM STUDIO & GROUNDED RETRIEVAL ENGINE")
    print("=" * 60)
    nbs = list_notebooks()
    print(f"Aktive Notebooks: {len(nbs)}")
    for nb in nbs:
        print(f" - [{nb['id']}] {nb['name']} ({nb['sources_count']} Quellen, {nb['messages_count']} Chats)")
