# Submission pack - Wacky Wheels Control Tower

Hitachi Hack the Highway (TAMU Datathon 2026). This folder has every portal upload item **except the demo video**. Nothing here was re-run against the enterprise server for packaging.

Start with `UPLOAD_CHECKLIST.md`.

## Portal uploads (what to send)

| Portal item | File(s) to upload |
|---|---|
| Action log | `action_log.jsonl` |
| Source code | `source_code.zip` |
| Ontology / graph export | `graph/ontology.ttl`, `graph/knowledge_graph.graphml`, `graph/graph_stats.json`, `graph/ontology_diagram.png` |
| Traces | entire `traces/` folder (exactly 15 files: E-01.json ... E-15.json) |
| Demo video | **not included** (submit separately) |
| Per-event summary and reason | `per_event_summary.md` |
| Design card | `design_card.pdf` (PNG also here as `design_card.png`) |
| Model citation | `MODEL_CITATION.md` |

## Full file list

| Path | What it is |
|---|---|
| `action_log.jsonl` | Scored log from `runs/final_v2/action_log.jsonl` |
| `source_code.zip` | App source for portal upload (`control_tower/`, `ui/`, `eval/`, `config/`, `tests/`, key `enterprise/` files) |
| `traces/E-01.json` ... `E-15.json` | Per-event traces (summary, reason, plan, verifier, graph paths) |
| `graph/ontology.ttl` | Ontology export (same code as Knowledge graph page) |
| `graph/knowledge_graph.graphml` | Full knowledge graph |
| `graph/graph_stats.json` | Node and edge totals |
| `graph/ontology_diagram.png` | Ontology diagram |
| `design_card.pdf` / `design_card.png` | One-page design card |
| `per_event_summary.md` | One row per event: category, gate, summary, reason |
| `MODEL_CITATION.md` | Model used on the scored run |
| `self_check_report.txt` | Independent 15/15 self-check |
| `run_summary.json` | Scored-run totals (writes, tokens, model) |
| `UPLOAD_CHECKLIST.md` | Short upload checklist |
| `README.md` | This file |

## How to run the app (from the full repo, not this zip alone)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run ui/app.py --server.port 8517
```

## How to run the self-check

```bash
python eval/self_check.py --log runs/final_v2/action_log.jsonl
```

## Model citation

`qwen2.5:3b-instruct` via Ollama, local. Details in `MODEL_CITATION.md` (numbers from `run_summary.json`).
