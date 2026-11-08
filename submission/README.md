# Submission pack - Wacky Wheels Control Tower

Hitachi Hack the Highway (TAMU Datathon 2026). This folder is a copy of the scored artifacts and supporting docs. Nothing here was re-run against the enterprise server for packaging.

## What each file is

| Path | Contents |
|---|---|
| `action_log.jsonl` | Scored write/read log from `runs/final_v2/action_log.jsonl` |
| `traces/E-01.json` ... `traces/E-15.json` | Per-event traces (summary, plan, verifier, graph paths, metrics) |
| `graph/ontology.ttl` | Ontology export (same as Knowledge graph page) |
| `graph/knowledge_graph.graphml` | Full knowledge graph export |
| `graph/graph_stats.json` | Node/edge totals by type |
| `graph/ontology_diagram.png` | Ontology schema diagram |
| `design_card.pdf` | One-page design card |
| `self_check_report.txt` | Independent self-check of the action log |
| `per_event_summary.md` | One row per event with category, gate, summary, reason |
| `README.md` | This file |

## How to run the app

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run ui/app.py --server.port 8517
```

The UI reads `traces/` and `exports/` only. It does not call the enterprise server.

## How to run the self-check

```bash
python eval/self_check.py --log runs/final_v2/action_log.jsonl
```

This replays the action log on a fresh enterprise with an independent rule implementation (no `control_tower` imports).

## Model citation

`qwen2.5:3b-instruct` via Ollama, local. Source: `traces/run_summary.json` (`llm_model`).

## Portal item mapping

| Portal item | File in this pack / repo |
|---|---|
| Action log | `action_log.jsonl` |
| Source code | repository root (`control_tower/`, `ui/`, `eval/`) |
| Ontology export | `graph/ontology.ttl`, `graph/knowledge_graph.graphml`, `graph/graph_stats.json`, `graph/ontology_diagram.png` |
| Traces | `traces/E-01.json` ... `traces/E-15.json` |
| Demo video | not included in this pack (submitted separately) |
| Per-event summary and reason | `per_event_summary.md` |
| Design card | `design_card.pdf` |
| Model citation | this README + `traces/run_summary.json` (`qwen2.5:3b-instruct`) |
