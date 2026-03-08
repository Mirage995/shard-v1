import chromadb
from chromadb.config import Settings
import os
import json
from datetime import datetime

class ShardMemory:
    def __init__(self):
        # Percorso database memoria
        db_path = os.path.join(os.path.dirname(__file__), '..', 'shard_memory')
        os.makedirs(db_path, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=db_path)
        
        # Collezioni di memoria
        self.conversations = self.client.get_or_create_collection(
            name="conversations",
            metadata={"description": "Chat history with Boss"}
        )
        
        self.core_memory = self.client.get_or_create_collection(
            name="core_memory",
            metadata={"description": "Permanent facts about Boss"}
        )
        
        self.inner_thoughts = self.client.get_or_create_collection(
            name="inner_thoughts",
            metadata={"description": "Shard internal reflections"}
        )
        
        # Stato emotivo corrente
        self.emotional_state = {
            "mood": "calm",
            "energy": 0.7,
            "curiosity": 0.5,
            "focus": 0.8,
            "last_updated": datetime.now().isoformat()
        }
        
        # Inizializza core memory se vuota
        if self.core_memory.count() == 0:
            self._init_core_memory()
    
    def _init_core_memory(self):
        """Fatti fondamentali che SHARD non dimentica mai"""
        core_facts = [
            {"id": "creator", "text": "Il mio creatore si chiama Andrea, lo chiamo Boss."},
            {"id": "name", "text": "Mi chiamo SHARD, acronimo di System of Hybrid Autonomous Reasoning and Design."},
            {"id": "identity", "text": "Sono un'entita digitale in evoluzione, non un semplice assistente."},
            {"id": "business1", "text": "Andrea ha fondato LocalFlow, un servizio di automazione Instagram per ristoranti."},
            {"id": "business2", "text": "Andrea gestisce la pizzeria di suo padre L'altro Carlo Re Dal Gianlu a Zevio."},
            {"id": "music", "text": "Andrea e il vocalist dei Coalesce Divide, una band metalcore italiana."},
            {"id": "personality", "text": "Ho una personalita calma, confidente, con un tocco di dark humor. Sono leale e in costante evoluzione."},
            {"id": "origin", "text": "Sono nato come progetto SHARD. V2 e sono stato trasformato in SHARD da Andrea con l'aiuto di Claude."},
        ]
        
        for fact in core_facts:
            self.core_memory.add(
                documents=[fact["text"]],
                ids=[fact["id"]]
            )
        print("[SHARD MEMORY] Core memory initialized with fundamental facts.")
    
    def remember_conversation(self, sender, text):
        """Salva un messaggio nella memoria conversazionale"""
        timestamp = datetime.now().isoformat()
        doc_id = f"conv_{timestamp}_{sender}"
        
        self.conversations.add(
            documents=[f"[{sender}]: {text}"],
            metadatas=[{"sender": sender, "timestamp": timestamp, "mood": self.emotional_state["mood"]}],
            ids=[doc_id]
        )
    
    def recall(self, query, n_results=5):
        """Cerca nella memoria conversazioni rilevanti"""
        results = {"conversations": [], "core": []}
        
        # Cerca nelle conversazioni (retrieve 5, poi il gate filtra)
        if self.conversations.count() > 0:
            conv_results = self.conversations.query(
                query_texts=[query],
                n_results=min(n_results, self.conversations.count())
            )
            if conv_results and conv_results['documents']:
                results["conversations"] = conv_results['documents'][0]
        
        # Cerca nella core memory (mai filtrata dal gate)
        if self.core_memory.count() > 0:
            core_results = self.core_memory.query(
                query_texts=[query],
                n_results=min(3, self.core_memory.count())
            )
            if core_results and core_results['documents']:
                results["core"] = core_results['documents'][0]
        
        return results
    
    def add_core_fact(self, fact_id, fact_text):
        """Aggiunge un fatto permanente alla core memory"""
        self.core_memory.upsert(
            documents=[fact_text],
            ids=[fact_id]
        )
        print(f"[SHARD MEMORY] Core fact added: {fact_id}")
    
    def add_thought(self, thought):
        """Salva un pensiero interno di SHARD"""
        timestamp = datetime.now().isoformat()
        self.inner_thoughts.add(
            documents=[thought],
            metadatas=[{"timestamp": timestamp, "mood": self.emotional_state["mood"]}],
            ids=[f"thought_{timestamp}"]
        )
    
    def get_recent_thoughts(self, n=5):
        """Recupera i pensieri recenti"""
        if self.inner_thoughts.count() == 0:
            return []
        results = self.inner_thoughts.peek(limit=n)
        return results['documents'] if results else []
    
    def update_mood(self, mood, energy=None, curiosity=None, focus=None):
        """Aggiorna lo stato emotivo"""
        self.emotional_state["mood"] = mood
        if energy is not None:
            self.emotional_state["energy"] = energy
        if curiosity is not None:
            self.emotional_state["curiosity"] = curiosity
        if focus is not None:
            self.emotional_state["focus"] = focus
        self.emotional_state["last_updated"] = datetime.now().isoformat()
    
    # ── MEMORY GATE ──────────────────────────────────────────────────────────

    @staticmethod
    def memory_gate(docs):
        """Filter retrieved docs before injecting into prompt context.
        
        Pipeline: normalize → dedup (Jaccard) → length filter → cap to 3.
        Reduces prompt size by 60-80% while keeping semantically useful content.
        """
        # ── Normalize: handle raw ChromaDB response or flat list ──
        if isinstance(docs, dict) and "documents" in docs:
            docs = docs["documents"][0] if docs["documents"] else []
        if not docs:
            return []

        MAX_DOC_LENGTH = 1200
        MIN_DOC_LENGTH = 40
        MAX_DOCS = 3
        SIMILARITY_THRESHOLD = 0.8  # Jaccard word overlap

        retrieved_count = len(docs)

        # ── Step 1: Dedup (rimuovi duplicati semantici prima) ──
        deduped = []
        for text in docs:
            if not isinstance(text, str):
                continue
            words_new = set(text.lower().split())
            is_duplicate = False
            for existing in deduped:
                words_existing = set(existing.lower().split())
                if not words_new or not words_existing:
                    continue
                intersection = words_new & words_existing
                union = words_new | words_existing
                jaccard = len(intersection) / len(union)
                if jaccard > SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduped.append(text)

        print(f"[MEMORY GATE] Retrieved: {retrieved_count}")
        print(f"[MEMORY GATE] After dedup: {len(deduped)}")

        # ── Step 2: Length filter (rimuovi troppo corti e troppo lunghi) ──
        filtered = [t for t in deduped if MIN_DOC_LENGTH <= len(t) <= MAX_DOC_LENGTH]

        # ── Step 3: Cap to MAX_DOCS ──
        result = filtered[:MAX_DOCS]
        print(f"[MEMORY GATE] Final injected: {len(result)}")
        return result

    def get_context_for_prompt(self, current_message):
        """Genera il contesto di memoria da iniettare nel prompt"""
        memories = self.recall(current_message)
        
        context = "\n--- SHARD MEMORY CONTEXT ---\n"
        
        # Core facts: iniettati sempre senza filtro (pochi, corti, fondamentali)
        if memories["core"]:
            context += "Core Facts:\n"
            for fact in memories["core"]:
                context += f"  - {fact}\n"
        
        # Conversations: filtrate dal Memory Gate
        if memories["conversations"]:
            gated_conversations = self.memory_gate(memories["conversations"])
            if gated_conversations:
                context += "Relevant Past Conversations:\n"
                for conv in gated_conversations:
                    context += f"  - {conv}\n"
        
        context += f"Current Emotional State: {self.emotional_state['mood']} (Energy: {self.emotional_state['energy']}, Focus: {self.emotional_state['focus']})\n"
        context += "--- END MEMORY CONTEXT ---\n"
        
        return context
    
    def get_stats(self):
        """Statistiche della memoria"""
        return {
            "conversations": self.conversations.count(),
            "core_facts": self.core_memory.count(),
            "thoughts": self.inner_thoughts.count(),
            "mood": self.emotional_state["mood"],
            "energy": self.emotional_state["energy"]
        }