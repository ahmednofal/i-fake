# i-fake

AI-powered fake traffic generator that poisons ad-tracking profiles with synthetic browsing behaviour.

## Setup

```bash
cp .env.example .env
# edit .env — add your API key
pip install -e .
playwright install chromium
```

## Usage

```bash
# Run one session immediately (headed browser for debugging)
i-fake run-once --headed

# Run 5 sessions then exit
i-fake start --sessions 5

# Run continuously on a schedule
i-fake start

# Generate a new persona
i-fake gen-persona

# List personas / sessions
i-fake personas
i-fake sessions

# Show config
i-fake config
```

## Providers

| Provider | env var | Notes |
|----------|---------|-------|
| `openai` | `IFAKE_OPENAI_API_KEY` | Default |
| `anthropic` | `IFAKE_ANTHROPIC_API_KEY` | Claude |
| `local` | `IFAKE_LOCAL_MODEL_URL` | Ollama / llama.cpp — fully private |

Switch with `IFAKE_AI_PROVIDER=local` in `.env`.
