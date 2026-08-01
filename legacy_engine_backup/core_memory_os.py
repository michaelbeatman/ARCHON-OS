import os
import re
import datetime
from typing import Dict, List, Set, Any, Optional
from pydantic import BaseModel, Field

# --- Pydantic Modelle für Kognitions-Speicher ---

class DialoguePage(BaseModel):
    role: str
    content: str
    timestamp: datetime.datetime
    summary: str
    keywords: List[str]

class MTMSegment(BaseModel):
    segment_id: str
    topic_name: str
    keywords: Set[str] = Field(default_factory=set)
    pages: List[DialoguePage] = Field(default_factory=list)
    access_count: int = 0
    last_accessed: datetime.datetime


class CoreMemoryOS:
    def __init__(self, db_storage: Any):
        self.storage = db_storage
        self.stm_limit = 7
        self.jaccard_threshold = 0.2
        self.lpm_heat_threshold = 3.0
        
        # In-Memory Cache (RAM) für STM und MTM
        self.stm_store: Dict[str, List[DialoguePage]] = {}  # session_id -> list of DialoguePages
        self.mtm_store: Dict[str, List[MTMSegment]] = {}  # session_id -> list of MTMSegments

    # --- Hilfsfunktionen für Textanalyse ---
    def _extract_keywords(self, text: str) -> List[str]:
        # Stoppwörter entfernen
        stop_words = {
            "the", "a", "and", "or", "in", "to", "for", "of", "is", "it", "that", "this",
            "der", "die", "das", "und", "ist", "es", "in", "zu", "mit", "den", "dem", "ein", "eine"
        }
        words = re.findall(r"\b[a-zA-Z0-9]{3,}\b", text.lower())
        return list(set([w for w in words if w not in stop_words]))

    def _generate_meta_chain_summary(self, text: str, keywords: List[str]) -> str:
        # Heuristische Zusammenfassung (erster Satz + Top-Keywords)
        sentences = re.split(r"[.!?]", text)
        first_sentence = sentences[0].strip() if sentences else text[:50]
        keyword_str = ", ".join(keywords[:4])
        return f"Meta-Chain: {first_sentence} (Keywords: {keyword_str})"

    def _calculate_jaccard(self, set_a: Set[str], set_b: Set[str]) -> float:
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a.intersection(set_b))
        union = len(set_a.union(set_b))
        return intersection / union

    # --- Short-Term Memory (STM) ---
    def add_interaction(self, session_id: str, role: str, content: str) -> DialoguePage:
        """
        Fügt eine Interaktion dem STM hinzu. Bei Überlauf (>7) wird das älteste Element ins MTM ausgelagert.
        """
        keywords = self._extract_keywords(content)
        summary = self._generate_meta_chain_summary(content, keywords)
        
        page = DialoguePage(
            role=role,
            content=content,
            timestamp=datetime.datetime.now(),
            summary=summary,
            keywords=keywords
        )

        self.stm_store.setdefault(session_id, [])
        self.stm_store[session_id].append(page)

        # FIFO Eviction ausführen bei Überlauf
        if len(self.stm_store[session_id]) > self.stm_limit:
            evicted_page = self.stm_store[session_id].pop(0)
            self._evict_to_mtm(session_id, evicted_page)

        return page

    # --- Mid-Term Memory (MTM) ---
    def _evict_to_mtm(self, session_id: str, page: DialoguePage):
        """
        Lagert eine DialoguePage mittels Jaccard-Ähnlichkeit ins MTM aus.
        """
        self.mtm_store.setdefault(session_id, [])
        segments = self.mtm_store[session_id]
        
        page_kw = set(page.keywords)
        best_segment: Optional[MTMSegment] = None
        best_score = 0.0

        for seg in segments:
            score = self._calculate_jaccard(page_kw, seg.keywords)
            if score > best_score:
                best_score = score
                best_segment = seg

        # Prüfe Jaccard-Schwellenwert
        if best_score >= self.jaccard_threshold and best_segment is not None:
            # Zu bestehendem Segment hinzufügen
            best_segment.pages.append(page)
            best_segment.keywords.update(page_kw)
            best_segment.access_count += 1
            best_segment.last_accessed = datetime.datetime.now()
            print(f"[MTM] Evicted page merged to segment '{best_segment.topic_name}' (Jaccard: {best_score:.2f})")
            
            # Prüfe, ob das Segment ein LPM-Upgrade verdient (Heat-Score)
            self._check_lpm_upgrade(session_id, best_segment)
        else:
            # Neues Segment erstellen
            new_id = f"seg_{len(segments) + 1}_{datetime.datetime.now().strftime('%M%S')}"
            topic_name = f"Topic {', '.join(page.keywords[:3]).title()}"
            new_segment = MTMSegment(
                segment_id=new_id,
                topic_name=topic_name,
                keywords=page_kw,
                pages=[page],
                access_count=1,
                last_accessed=datetime.datetime.now()
            )
            segments.append(new_segment)
            print(f"[MTM] Opened new segment '{topic_name}' for page.")

    # --- Long-Term Persona Memory (LPM) ---
    def _check_lpm_upgrade(self, session_id: str, segment: MTMSegment):
        """
        Berechnet den Heat-Score des MTM-Segments. Bei Überschreiten des Thresholds werden Fakten ins LPM extrahiert.
        """
        now = datetime.datetime.now()
        days_since = (now - segment.last_accessed).total_seconds() / 86400.0
        # Heat Score: Häufigkeit dividiert durch Zeitabstand
        heat_score = segment.access_count * (1.0 / (days_since + 1.0))

        if heat_score >= self.lpm_heat_threshold:
            print(f"[LPM] High Heat Score ({heat_score:.2f} >= {self.lpm_heat_threshold:.2f}) on '{segment.topic_name}'. Extracting facts...")
            self._extract_and_persist_facts(segment)

    def _extract_and_persist_facts(self, segment: MTMSegment):
        """
        Sucht nach Mustern für User Preferences und Agent Traits und speichert diese persistent in SQL.
        """
        # Mustererkennung
        user_pref_regex = re.compile(r"(?:i prefer|my preference is|ich bevorzuge)\s+([a-zA-Z0-9\s_\-\.]+)", re.IGNORECASE)
        agent_trait_regex = re.compile(r"(?:agent should|you should|du solltest)\s+([a-zA-Z0-9\s_\-\.]+)", re.IGNORECASE)

        for page in segment.pages:
            content = page.content
            
            # 1. User Preferences
            for match in user_pref_regex.finditer(content):
                fact = match.group(1).strip().rstrip(".,?!;:")
                key = f"user_pref_{re.sub(r'[^a-z0-9_]', '_', fact[:20].lower()).strip('_')}"
                # Persistent abspeichern (user_profile)
                self.storage.set_preference(key, fact)
                print(f"[LPM Fact] Saved User Preference: {key} -> {fact}")

            # 2. Agent Traits
            for match in agent_trait_regex.finditer(content):
                trait = match.group(1).strip().rstrip(".,?!;:")
                knowledge_id = f"trait_{re.sub(r'[^a-z0-9_]', '_', trait[:20].lower()).strip('_')}"
                # Persistent abspeichern (learnings)
                self.storage.save_learning(
                    knowledge_id=knowledge_id,
                    agent_id="system",
                    key="agent_behavior",
                    value=trait
                )
                print(f"[LPM Fact] Saved Agent Trait: {knowledge_id} -> {trait}")

    # --- Retrieval Pipeline ---
    def retrieve_memory_context(self, session_id: str, query: str, m_segments: int = 2) -> Dict[str, Any]:
        """
        Sucht parallel in STM, MTM und LPM nach passenden Kontexten.
        """
        query_kw = set(self._extract_keywords(query))
        
        # 1. STM abrufen
        stm_pages = self.stm_store.get(session_id, [])
        stm_snippets = [p.summary for p in stm_pages]
        
        # 2. MTM abrufen (Jaccard Suche über Segmente)
        mtm_segments = self.mtm_store.get(session_id, [])
        scored_segments = []
        for seg in mtm_segments:
            score = self._calculate_jaccard(query_kw, seg.keywords)
            scored_segments.append((score, seg))
            
        # Sortiere MTM nach Score
        scored_segments.sort(key=lambda x: x[0], reverse=True)
        top_segments = [seg for score, seg in scored_segments[:m_segments] if score > 0]

        # 3. LPM abrufen
        # Hole alle gelernten Benutzerpräferenzen aus `user_profile` und Anpassungen aus `learnings`
        # Wir durchsuchen das DB Schema und rufen relevante Infos ab
        user_kb = {}
        agent_traits = []
        
        conn = self.storage._get_connection()
        try:
            # Lade alle user_profile Keys, die mit 'user_pref_' beginnen
            pref_rows = conn.execute("SELECT key, value FROM user_profile WHERE key LIKE 'user_pref_%'").fetchall()
            for r in pref_rows:
                user_kb[r["key"]] = r["value"]
                
            # Lade alle Traits aus learnings
            learning_rows = conn.execute("SELECT key, value FROM learnings WHERE key = 'agent_behavior'").fetchall()
            for r in learning_rows:
                agent_traits.append(r["value"])
        finally:
            conn.close()

        # Formatierung der Prompt-Injektion
        prompt_injection = ""
        if user_kb or agent_traits or top_segments:
            prompt_injection = "\n=== KOGNITIVER SPEICHER-KONTEXT ===\n"
            if user_kb:
                prompt_injection += "User Preferences:\n"
                for k, v in user_kb.items():
                    prompt_injection += f" - {v}\n"
            if agent_traits:
                prompt_injection += "Agent Traits:\n"
                for t in agent_traits:
                    prompt_injection += f" - {t}\n"
            if top_segments:
                prompt_injection += "Relevant Past Topics:\n"
                for seg in top_segments:
                    prompt_injection += f" - Segment '{seg.topic_name}': {len(seg.pages)} interactions\n"
            prompt_injection += "===================================\n"

        return {
            "stm_snippets": stm_snippets,
            "top_segments": [s.topic_name for s in top_segments],
            "user_kb": user_kb,
            "agent_traits": agent_traits,
            "prompt_injection": prompt_injection
        }
