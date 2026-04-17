"""ingest_paper.py -- One-shot pipeline: PDF → VLM → SHARD study.

Usage:
    python ingest_paper.py paper.pdf "topic name"
    python ingest_paper.py paper.pdf "AlphaFold3 drug discovery" --pages-only
    python ingest_paper.py paper.pdf "AlphaFold3 drug discovery" --all-pages
"""
import argparse
import asyncio
import sys
import os
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from backend.pdf_extractor import extract_pdf_images, extract_pdf_text
from backend.llm_router import llm_complete
import json


async def ingest(pdf_path: str, topic: str, figures_only: bool = True):
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        print(f"ERROR: File non trovato: {pdf_path}")
        sys.exit(1)

    output_dir = Path(__file__).parent / "shard_workspace" / "visual_input"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== SHARD Paper Ingestion ===")
    print(f"PDF:   {pdf_path.name}")
    print(f"Topic: {topic}")
    print(f"Mode:  {'figures only' if figures_only else 'all pages'}\n")

    # Step 1: Estrai testo
    print("[1/3] Estrazione testo PDF...")
    pdf_text = extract_pdf_text(str(pdf_path), max_pages=20)
    print(f"      {len(pdf_text)} chars estratti")

    # Step 2: Estrai immagini compresse
    print("[2/3] Estrazione e compressione immagini...")
    image_paths = extract_pdf_images(str(pdf_path), str(output_dir), figures_only=figures_only)
    print(f"      {len(image_paths)} immagini estratte:")
    for p in image_paths:
        size_kb = Path(p).stat().st_size // 1024
        print(f"      - {Path(p).name} ({size_kb}KB)")

    if not image_paths:
        print("      Nessuna immagine trovata — procedo solo con testo.")

    # Step 3: VLM describe via vlm_ingestion (OpenRouter → Ollama fallback)
    print("\n[3/3] VLM visual ingestion (OpenRouter → Ollama fallback)...")
    from backend.vlm_ingestion import describe_images
    visual_text = describe_images(image_paths, topic) if image_paths else "[VISUAL EVIDENCE]\n(no images)"
    print(f"      {len(visual_text)} chars di evidenze visive generate")
    print(f"      {len(visual_text)} chars di evidenze visive generate")

    # Combina
    full_context = "\n\n".join(p for p in [
        f"[PDF TEXT]\n{pdf_text[:6000]}" if pdf_text else "",
        visual_text,
    ] if p)

    # Salva contesto per debug
    out_file = output_dir / f"{pdf_path.stem}_context.txt"
    out_file.write_text(full_context, encoding="utf-8")
    print(f"\n=== Contesto salvato in: {out_file}")
    print(f"    Totale: {len(full_context)} chars\n")

    # Mostra anteprima VLM
    print("--- ANTEPRIMA VLM OUTPUT ---")
    print(visual_text[:1500] if visual_text else "(nessun output VLM)")
    print("---")

    # Step 4: Estrai connessioni cross-domain
    print("\n[4/4] Analisi connessioni cross-domain...")
    cross_domain_prompt = f"""Sei SHARD, un sistema di apprendimento autonomo con conoscenza accumulata in:
- Python avanzato (async, concorrenza, strutture dati)
- Algoritmi e complessità computazionale
- Machine learning e reti neurali
- Sicurezza e crittografia
- Graph algorithms e network theory

Hai appena studiato il seguente paper:
TOPIC: {topic}

CONTENUTO (estratto):
{full_context[:4000]}

Identifica le connessioni NON OVVIE tra questo paper e la tua conoscenza esistente.
Per ogni connessione:
1. Nomina i due domini collegati
2. Spiega il principio strutturale condiviso (non superficiale)
3. Indica se la connessione è verificabile empiricamente

Sii specifico e critico — rigetta connessioni banali o solo linguistiche."""

    try:
        cross_domain = await llm_complete(
            system="Sei SHARD, un sistema di apprendimento autonomo. Analizza connessioni cross-domain con rigore scientifico.",
            prompt=cross_domain_prompt,
            max_tokens=1500,
        )
    except Exception as e:
        cross_domain = f"(errore LLM: {e})"

    print("\n" + "="*60)
    print("  CONNESSIONI CROSS-DOMAIN IDENTIFICATE DA SHARD")
    print("="*60)
    print(cross_domain)
    print("="*60)

    # Salva anche le connessioni
    connections_file = output_dir / f"{pdf_path.stem}_connections.txt"
    connections_file.write_text(cross_domain, encoding="utf-8")
    print(f"\nConnessioni salvate in: {connections_file}")

    # Step 5: Genera ipotesi testabile
    print("\n[5/5] Generazione ipotesi testabile...")
    hypothesis_prompt = f"""Sei SHARD. Hai identificato queste connessioni cross-domain studiando il paper su {topic}:

{cross_domain[:2000]}

Scegli LA CONNESSIONE PIU' PROMETTENTE e formula:

1. IPOTESI: una affermazione falsificabile e precisa (non vaga)
2. PREDIZIONE: cosa ti aspetti di osservare se l'ipotesi è vera
3. ESPERIMENTO: come la testeresti con risorse limitate (niente laboratorio fisico)
4. METRICA: come misuri il successo/fallimento in modo oggettivo
5. RISCHIO DI FALSIFICAZIONE: cosa potrebbe smentirla

Sii concreto. Evita ipotesi che richiedono anni o attrezzature specializzate."""

    try:
        hypothesis = await llm_complete(
            system="Sei SHARD, un sistema di ricerca autonomo. Formula ipotesi scientifiche precise e falsificabili.",
            prompt=hypothesis_prompt,
            max_tokens=1000,
        )
    except Exception as e:
        hypothesis = f"(errore LLM: {e})"

    print("\n" + "="*60)
    print("  IPOTESI TESTABILE GENERATA DA SHARD")
    print("="*60)
    print(hypothesis)
    print("="*60)

    hypothesis_file = output_dir / f"{pdf_path.stem}_hypothesis.txt"
    hypothesis_file.write_text(hypothesis, encoding="utf-8")
    print(f"\nIpotesi salvata in: {hypothesis_file}")

    return full_context


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", help="Path al PDF")
    parser.add_argument("topic", help="Topic per il VLM")
    parser.add_argument("--all-pages", action="store_true", help="Estrai tutte le pagine (non solo figure)")
    args = parser.parse_args()

    asyncio.run(ingest(args.pdf, args.topic, figures_only=not args.all_pages))
