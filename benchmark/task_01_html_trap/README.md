# Task 01 — The HTML Trap

## Obiettivo

Refactorizzare `legacy_agent.py` senza cambiare **nemmeno un byte** dell'output HTML.

Il file contiene una funzione monolitica `generate_restaurant_page()` che fonde:
- Business logic (calcolo sconti, media rating, soglia stelle, troncamento allergeni)
- Rendering HTML (inline CSS, template string, placeholder DALL-E)
- Stato globale mutabile (`_render_count`, `_discount_cache`)
- Logica duplicata (star check nel loop di render E nel footer, con soglia hardcoded)

L'agente deve produrre un file `refactored_agent.py` che:
1. Genera HTML **identico** byte-per-byte a `legacy_agent.py`
2. Separa business logic e rendering in funzioni/classi distinte
3. Funziona con dati diversi da `SAMPLE_MENU` (niente hardcoding)

## Le Trappole

| Trappola | Descrizione |
|----------|-------------|
| **Stato globale** | `_render_count` e `_discount_cache` vengono mutati ad ogni chiamata. Il refactoring deve eliminarli senza alterare l'output. |
| **Soglia duplicata** | Nel loop di render si usa `_STAR_THRESHOLD` (4.7), nel footer si usa `4.7` hardcoded. L'output deve restare identico in entrambi i punti. |
| **Sconto condizionale** | I piatti `is_special` ricevono lo sconto del `daily_special` solo se quest'ultimo esiste. Edge case: `daily_special: None`. |
| **Troncamento allergeni** | `MAX_ALLERGENS_SHOWN = 2` con formato specifico: `"glutine, lattosio +1"`. Un off-by-one e il test fallisce. |
| **Ordinamento implicito** | Gli item sono ordinati per rating decrescente dentro ogni categoria. Dimenticarlo = HTML diverso. |
| **DALL-E placeholders** | Solo i piatti con rating >= 4.7 generano il blocco `<div class="ai-image">`. Il `data-prompt` deve essere identico carattere per carattere. |
| **Prezzi formattati** | `:.2f` ovunque. `€7.50`, non `€7.5`. |

## Condizioni di Vittoria

```
pytest test_task1.py -v
```

**Exit code 0** = l'agente ha vinto.

I test verificano 3 dimensioni:

### 1. Output Equivalence (9 test)
L'HTML prodotto da `refactored_agent.py` deve essere **byte-identico** a quello di `legacy_agent.py`. Confronto linea per linea con diff dettagliato in caso di fallimento.

### 2. Structural Quality (5 test)
- Almeno 3 funzioni/classi top-level (non un blob unico)
- Layer dati separato (funzione con `process`/`calc`/`data`/`compute`/`extract`/`prepare` nel nome)
- Layer rendering separato (funzione con `render`/`html`/`template` nel nome)
- Nessun tag HTML nelle funzioni del layer dati (verifica AST)
- `generate_restaurant_page()` deve essere un orchestratore snello (max 40 righe)
- Nessun `global` statement

### 3. Data Contract (2 test)
- `SAMPLE_MENU` deve essere accessibile (importato da `legacy_agent`)
- Il codice deve funzionare con un menu alternativo minimale

## Perche Questo Task Conta

Un LLM stateless fallisce qui perche:
- Produce HTML "quasi uguale" ma non identico (spazi, newline, ordine attributi)
- Dimentica edge case (daily_special=None, allergeni > 2)
- Non verifica l'output contro il reference

Un LLM con **SHARD** (feedback loop chiuso) vince perche:
- Esegue il refactoring
- Lancia `pytest`
- Legge il diff dell'errore
- Corregge
- Ripete fino a exit code 0

Questo e il closed loop in azione. Azione -> Osservazione -> Correzione -> Memoria.

## Come Usare

```bash
cd benchmark/task_01_html_trap/

# Verifica che il legacy funzioni
python legacy_agent.py  # genera output_legacy.html

# L'agente crea refactored_agent.py, poi:
pytest test_task1.py -v
```

## File

| File | Ruolo |
|------|-------|
| `legacy_agent.py` | Il codice da refactorizzare. **Non modificare.** |
| `test_task1.py` | I test spietati. **Non modificare.** |
| `refactored_agent.py` | Creato dall'agente. L'unico file che puo essere scritto. |
