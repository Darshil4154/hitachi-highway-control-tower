# Model citation

Model: qwen2.5:3b-instruct
Runtime: Ollama, local
Temperature: 0 (see control_tower/config.py / run)

Usage on the scored run (from traces/run_summary.json):
- LLM calls: 15
- Prompt tokens: 17149
- Completion tokens: 2267
- Total tokens: 19416

The LLM only classifies each message and copies exact phrases. Ids, dates, affected sets, slots, loaners, and every write are computed by code.
