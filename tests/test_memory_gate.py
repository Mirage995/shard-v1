"""Unit tests for ShardMemory.memory_gate()

The memory_gate function is a @staticmethod that doesn't depend on ChromaDB
or any instance state, so we test it directly by extracting the logic.
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Mock chromadb before importing memory module
sys.modules['chromadb'] = MagicMock()
sys.modules['chromadb.config'] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from memory import ShardMemory


class TestMemoryGate(unittest.TestCase):
    """Tests for the memory_gate static method."""

    def test_empty_list_returns_empty(self):
        self.assertEqual(ShardMemory.memory_gate([]), [])

    def test_none_returns_empty(self):
        self.assertEqual(ShardMemory.memory_gate(None), [])

    def test_filters_long_docs(self):
        """Documents over 1200 chars should be removed."""
        short = "This is a short relevant document about SHARD." * 2  # ~90 chars
        long_doc = "x" * 1300  # Over 1200
        result = ShardMemory.memory_gate([short, long_doc])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], short)

    def test_filters_short_docs(self):
        """Documents under 40 chars should be removed (noise)."""
        too_short = "Hi"
        good = "This is a meaningful conversation about the project and its goals."
        result = ShardMemory.memory_gate([too_short, good])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], good)

    def test_removes_duplicates(self):
        """Near-identical documents should be deduplicated."""
        doc1 = "Il Boss ha chiesto di implementare il sistema di memoria persistente per SHARD"
        doc2 = "Il Boss ha chiesto di implementare il sistema di memoria persistente per SHARD oggi"
        doc3 = "SHARD ha completato lo studio su machine learning con score 8.5"
        result = ShardMemory.memory_gate([doc1, doc2, doc3])
        self.assertEqual(len(result), 2)  # doc2 is a near-duplicate of doc1

    def test_caps_at_3_docs(self):
        """Output should never exceed 3 documents."""
        docs = [f"Document number {i} with enough unique length to pass both the minimum and dedup filter easily and correctly." for i in range(10)]
        result = ShardMemory.memory_gate(docs)
        self.assertLessEqual(len(result), 3)

    def test_handles_chromadb_dict_format(self):
        """Should normalize raw ChromaDB response format."""
        chromadb_response = {
            "documents": [
                [
                    "First relevant conversation about Python programming and SHARD development.",
                    "Second conversation about system architecture and design patterns."
                ]
            ]
        }
        result = ShardMemory.memory_gate(chromadb_response)
        self.assertEqual(len(result), 2)

    def test_handles_chromadb_empty_dict(self):
        """Should handle empty ChromaDB response gracefully."""
        result = ShardMemory.memory_gate({"documents": [[]]})
        self.assertEqual(result, [])

    def test_dedup_before_length_filter(self):
        """Dedup should happen before length filter to preserve unique short docs."""
        # Two similar long docs and one unique short doc
        long1 = "A" * 500 + " concetto di machine learning applicato alla robotica industriale"
        long2 = "A" * 500 + " concetto di machine learning applicato alla robotica industriale oggi"
        unique_short = "SHARD ha scoperto una nuova connessione tra quantum computing e neural networks."
        result = ShardMemory.memory_gate([long1, long2, unique_short])
        # long2 is a duplicate of long1, so we get long1 + unique_short
        self.assertEqual(len(result), 2)
        self.assertIn(unique_short, result)

    def test_preserves_order(self):
        """Original order should be preserved (most relevant first from ChromaDB)."""
        docs = [
            "Prima conversazione rilevante sulla memoria di SHARD e le sue funzionalita principali.",
            "Seconda conversazione sul sistema RPG e le certificazioni di SHARD agent nel progetto.",
            "Terza conversazione sulla coscienza artificiale e l'evoluzione del sistema complesso.",
        ]
        result = ShardMemory.memory_gate(docs)
        self.assertEqual(result, docs)

    def test_non_string_items_skipped(self):
        """Non-string items in the list should be silently skipped."""
        docs = [
            "Valid document with enough content to pass the minimum length filter correctly.",
            None,
            42,
            "Another valid doc that passes the filter for minimum length requirement."
        ]
        result = ShardMemory.memory_gate(docs)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
