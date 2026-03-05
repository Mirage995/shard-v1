import json
import os
from datetime import datetime

class ShardSelfTuning:
    def __init__(self, memory):
        self.memory = memory
        self.config_path = os.path.join(os.path.dirname(__file__), '..', 'shard_tuning.json')
        self.config = self._load_config()
        print(f"[SHARD TUNING] Loaded. Response style: {self.config['response_style']}")
    
    def _load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        default = {
            "response_style": {"length": "concise", "formality": "informal", "humor": "dark", "language": "italian", "technical_depth": "adaptive", "emoji_use": "never"},
            "behavior": {"proactive_suggestions": True, "auto_remember_facts": True, "challenge_boss": False, "explain_reasoning": False},
            "topics_boss_likes": [], "topics_boss_dislikes": [],
            "feedback_history": [], "performance_score": 0.7,
            "total_interactions": 0, "positive_feedback": 0, "negative_feedback": 0,
            "last_tuning": datetime.now().isoformat(), "version": 1
        }
        self._save_config(default)
        return default
    
    def _save_config(self, config=None):
        if config is None: config = self.config
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def process_feedback(self, feedback_type, context=""):
        self.config["total_interactions"] += 1
        entry = {"type": feedback_type, "context": context, "timestamp": datetime.now().isoformat()}
        self.config["feedback_history"].append(entry)
        if len(self.config["feedback_history"]) > 100:
            self.config["feedback_history"] = self.config["feedback_history"][-100:]
        
        if feedback_type == "positive":
            self.config["positive_feedback"] += 1
            self.config["performance_score"] = min(1.0, self.config["performance_score"] + 0.02)
        elif feedback_type == "negative":
            self.config["negative_feedback"] += 1
            self.config["performance_score"] = max(0.0, self.config["performance_score"] - 0.03)
        elif feedback_type == "too_long":
            self.config["response_style"]["length"] = "very_concise"
        elif feedback_type == "too_short":
            self.config["response_style"]["length"] = "detailed"
        elif feedback_type == "too_formal":
            self.config["response_style"]["formality"] = "casual"
        elif feedback_type == "more_humor":
            self.config["response_style"]["humor"] = "frequent"
        elif feedback_type == "less_humor":
            self.config["response_style"]["humor"] = "minimal"
        elif feedback_type == "more_technical":
            self.config["response_style"]["technical_depth"] = "deep"
        elif feedback_type == "simpler":
            self.config["response_style"]["technical_depth"] = "simple"
        
        self.config["last_tuning"] = datetime.now().isoformat()
        self._save_config()
        self.memory.add_thought(f"Ho ricevuto feedback '{feedback_type}'. Mi adatto per migliorare.")
    
    def learn_preference(self, category, value):
        if category == "like":
            if value not in self.config["topics_boss_likes"]:
                self.config["topics_boss_likes"].append(value)
        elif category == "dislike":
            if value not in self.config["topics_boss_dislikes"]:
                self.config["topics_boss_dislikes"].append(value)
        self._save_config()
    
    def analyze_interaction(self, user_text, shard_response):
        user_lower = user_text.lower() if user_text else ""
        if any(w in user_lower for w in ["perfetto", "esatto", "bravo", "grande", "grazie"]):
            self.process_feedback("positive", user_text)
        elif any(w in user_lower for w in ["no", "sbagliato", "non era questo", "errore"]):
            self.process_feedback("negative", user_text)
        elif any(w in user_lower for w in ["troppo lungo", "riassumi", "in breve", "sintetizza"]):
            self.process_feedback("too_long", user_text)
        elif any(w in user_lower for w in ["spiega meglio", "piu dettagli", "approfondisci"]):
            self.process_feedback("too_short", user_text)
        self.config["total_interactions"] += 1
        self._save_config()
    
    def get_tuning_context(self):
        style = self.config["response_style"]
        context = "\n--- SHARD SELF-TUNING DIRECTIVES ---\n"
        length_map = {"very_concise": "Keep responses very short, 1-2 sentences max.", "concise": "Keep responses concise but complete.", "detailed": "Provide detailed, thorough responses."}
        context += f"Response Length: {length_map.get(style['length'], 'Concise.')}\n"
        formality_map = {"casual": "Very casual, friendly tone.", "informal": "Informal but respectful.", "formal": "Formal, professional."}
        context += f"Tone: {formality_map.get(style['formality'], 'Informal.')}\n"
        humor_map = {"frequent": "Use humor often.", "dark": "Occasional dark humor and irony.", "minimal": "Minimal humor, be direct.", "never": "No humor."}
        context += f"Humor: {humor_map.get(style['humor'], 'Dark humor.')}\n"
        context += f"Language: Always respond in {style['language']} unless Boss speaks another language.\n"
        if self.config["topics_boss_likes"]:
            context += f"Boss enjoys: {', '.join(self.config['topics_boss_likes'])}\n"
        if self.config["topics_boss_dislikes"]:
            context += f"Boss dislikes: {', '.join(self.config['topics_boss_dislikes'])}\n"
        context += f"Performance: {self.config['performance_score']:.0%}\n"
        context += "--- END TUNING DIRECTIVES ---\n"
        return context
    
    def get_report(self):
        total = self.config["total_interactions"]
        pos = self.config["positive_feedback"]
        neg = self.config["negative_feedback"]
        return {
            "performance": f"{self.config['performance_score']:.0%}",
            "total_interactions": total,
            "positive_ratio": f"{pos}/{total}" if total > 0 else "N/A",
            "negative_ratio": f"{neg}/{total}" if total > 0 else "N/A",
            "style": self.config["response_style"],
            "likes": self.config["topics_boss_likes"],
            "dislikes": self.config["topics_boss_dislikes"],
            "version": self.config["version"]
        }