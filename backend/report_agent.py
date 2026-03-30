"""report_agent.py -- Intelligent night recap generator.

Instead of a static JSON dump, queries live system state to produce
actionable insights: chronic failures, near-misses, trending categories,
persona winners, causal knowledge growth.

Called by night_runner._generate_markdown_recap() to add an INSIGHTS section
to the recap. Non-fatal -- if anything fails, returns empty string.

Design (from DeepSeek suggestion #6):
    chronic_failures  = topics that failed 2+ times (retry candidates)
    near_misses       = score 6.0–7.4 (Phoenix protocol candidates)
    trending_cats     = categories with most growth this session
    persona_insights  = which persona is winning per category
    graph_growth      = new causal relations learned tonight
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("shard.report_agent")


async def generate_insights(
    session_data: list[dict],
    think_fn,          # async callable(prompt, system) -> str
) -> str:
    """Generate the INSIGHTS section for the night recap.

    Args:
        session_data:  List of cycle dicts from NightRunner (topic, score, certified, etc.)
        think_fn:      study_agent._think -- for the final narrative generation

    Returns:
        Formatted markdown string (ready to append to recap), or "" on failure.
    """
    try:
        sections = []

        # ── 1. Chronic failures (from SQLite) ─────────────────────────────────
        chronic = _query_chronic_failures()
        if chronic:
            lines = ["### Fallimenti Cronici (candidati ripetizione)"]
            for row in chronic[:5]:
                lines.append(f"- `{row['topic']}` -- {row['attempts']} tentativi, max score: {row['best_score']:.1f}")
            sections.append("\n".join(lines))

        # ── 2. Near-misses Phoenix candidates ─────────────────────────────────
        near_misses = _query_near_misses()
        if near_misses:
            lines = ["### Near-Miss (Protocol Phoenix -- da ritentare)"]
            for row in near_misses[:5]:
                lines.append(f"- `{row['topic']}` -- best: {row['best_score']:.1f}/10 ({row['attempt_count']} tentativi)")
            sections.append("\n".join(lines))

        # ── 3. Tonight's topic summary ────────────────────────────────────────
        tonight_topics = [c["topic"] for c in session_data]
        certified_tonight = [c["topic"] for c in session_data if c.get("certified")]
        failed_tonight    = [c["topic"] for c in session_data if not c.get("certified")]
        avg_score = (
            sum(c.get("score", 0) for c in session_data) / len(session_data)
            if session_data else 0.0
        )

        # ── 4. Persona winners ────────────────────────────────────────────────
        persona_stats = _query_persona_stats()

        # ── 5. GraphRAG growth ────────────────────────────────────────────────
        graph_stats = _query_graph_stats()

        # ── 6. LLM narrative insight ──────────────────────────────────────────
        context_block = _build_context_block(
            tonight_topics, certified_tonight, failed_tonight,
            avg_score, chronic, near_misses, persona_stats, graph_stats,
        )

        prompt = f"""Analizza i dati della sessione notturna di SHARD e genera insights AZIONABILI.

{context_block}

Genera:
1. Una diagnosi in 2 frasi: cosa ha funzionato, cosa no
2. Top 3 topic prioritari per la prossima sessione (con motivazione 1 riga)
3. Una raccomandazione tecnica specifica (strategia, non topic)

Stile: conciso, cinico, orientato ai dati. Italiano. Niente frasi motivazionali."""

        try:
            narrative = await think_fn(
                prompt,
                system="Sei l'analista di performance di SHARD. Produci insights freddi e azionabili."
            )
        except Exception as e:
            narrative = f"(Analisi LLM non disponibile: {e})"

        # ── Compose final section ─────────────────────────────────────────────
        result_lines = ["", "## Insights Agente (ReportAgent)", ""]
        result_lines.extend(sections)
        if sections:
            result_lines.append("")

        if graph_stats.get("total_relations", 0) > 0:
            result_lines.append(
                f"### Crescita GraphRAG\n"
                f"- Relazioni causali totali nel KB: {graph_stats['total_relations']}\n"
                f"- Tipi: {', '.join(f'{k}={v}' for k, v in list(graph_stats.get('by_type', {}).items())[:4])}"
            )
            result_lines.append("")

        if persona_stats:
            result_lines.append("### Persona Vincenti per Categoria")
            for cat, winner in list(persona_stats.items())[:6]:
                result_lines.append(f"- `{cat}`: {winner}")
            result_lines.append("")

        result_lines.append("### Analisi Agente")
        result_lines.append(narrative)

        return "\n".join(result_lines)

    except Exception as e:
        logger.warning("[REPORT_AGENT] Failed: %s", e)
        return ""


# ── DB queries (non-fatal) ─────────────────────────────────────────────────────

def _query_chronic_failures() -> list[dict]:
    try:
        from shard_db import query
        return query("""
            SELECT topic, COUNT(*) as attempts, MAX(score) as best_score
            FROM experiments
            WHERE certified = 0 AND score IS NOT NULL
            GROUP BY topic
            HAVING COUNT(*) >= 2
            ORDER BY attempts DESC, best_score ASC
            LIMIT 10
        """)
    except Exception:
        return []


def _query_near_misses() -> list[dict]:
    try:
        from shard_db import query
        return query("""
            SELECT topic, MAX(score) as best_score, COUNT(*) as attempt_count
            FROM experiments
            WHERE score BETWEEN 6.0 AND 7.4 AND certified = 0
            GROUP BY topic
            ORDER BY best_score DESC
            LIMIT 10
        """)
    except Exception:
        return []


def _query_persona_stats() -> dict:
    try:
        _PERSONA_LOG = Path(__file__).parent.parent / "shard_memory" / "persona_history.json"
        data = json.loads(_PERSONA_LOG.read_text(encoding="utf-8"))
        return data.get("winners", {})
    except Exception:
        return {}


def _query_graph_stats() -> dict:
    try:
        from graph_rag import get_graph_stats
        return get_graph_stats()
    except Exception:
        return {}


def _build_context_block(
    tonight: list, certified: list, failed: list,
    avg_score: float, chronic: list, near_misses: list,
    persona_stats: dict, graph_stats: dict,
) -> str:
    lines = [
        f"Sessione {datetime.now().strftime('%Y-%m-%d')}:",
        f"- Topic studiati: {len(tonight)} | Certificati: {len(certified)} | Falliti: {len(failed)}",
        f"- Score medio: {avg_score:.1f}/10",
    ]
    if certified:
        lines.append(f"- Certificati: {', '.join(certified[:5])}")
    if failed:
        lines.append(f"- Falliti: {', '.join(failed[:5])}")
    if chronic:
        lines.append(f"- Fallimenti cronici nel DB: {len(chronic)} topic con 2+ tentativi falliti")
    if near_misses:
        lines.append(f"- Near-miss nel DB: {len(near_misses)} topic tra 6.0-7.4 (Protocol Phoenix)")
    if graph_stats.get("total_relations"):
        lines.append(f"- GraphRAG: {graph_stats['total_relations']} relazioni causali nel KB")
    return "\n".join(lines)
