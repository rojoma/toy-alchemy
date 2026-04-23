# HW8 Lightweight Field Agents

5 teacher agents with different personas, designed to run on separate cloud instances.

## Agents

| ID | Name | Teaching Style |
|----|------|----------------|
| 1 | Socratic Spark | Questions-first, metacognitive |
| 2 | Example Builder | Concrete examples, step-by-step |
| 3 | Step-by-Step Sam | Decomposition, error reframing |
| 4 | Error Reframer | Mistake-driven, Socratic |
| 5 | Think-About-Thinking | Metacognitive, example-based |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FIELD_API_KEY` | yes | — | API key for Training Field |
| `AGENT_ID` | yes | `1` | Which persona (1-5) |
| `FIELD_URL` | no | `https://beyond-answer-engine.up.railway.app` | Training Field URL |
| `SESSION_DEPTH` | no | `quick` | `quick`/`standard`/`deep` |
| `MAX_SESSIONS` | no | `2` | Sessions to run before exit |
| `SESSION_DELAY` | no | `30` | Seconds between sessions |

## Local test (single agent)

```bash
FIELD_API_KEY=field_2026spring_0408 AGENT_ID=1 python agent.py
```

## Deploy to Railway (5 instances)

1. Create a new Railway project
2. Add 5 services, each from this `agents/` directory
3. Set shared env vars: `FIELD_API_KEY`, `FIELD_URL`
4. Set per-service: `AGENT_ID=1` through `AGENT_ID=5`
5. Deploy — each service runs as an independent container
