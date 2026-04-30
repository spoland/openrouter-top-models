# OpenRouter Top Models Dashboard

A FastAPI application that fetches all available text models from [OpenRouter](https://openrouter.ai), scores them by capabilities, recency, and value, and presents a clean UI showing:

- **Best General Models** — top all-rounders ranked by capability (context length, multimodal support, tools, reasoning, etc.)
- **Per-Category Rankings** — for each OpenRouter category (Programming, Roleplay, Marketing, Science, etc.)
  - **Top 10 Overall** — best models regardless of cost/provider
  - **Top 10 Non-Frontier** — best affordable models that are **not** from the expensive big-tech tier

## How rankings work

Models are scored heuristically because OpenRouter does not expose a public benchmark/rankings API. The scoring considers:

- **Context length** — longer context = higher score
- **Supported parameters** — tools, reasoning, structured outputs, etc.
- **Multimodal inputs** — vision, audio, video support
- **Recency** — newer models get a boost
- **Price / value** — cheaper models get a value bonus (weighted higher in category rankings than in "Best General")
- **Category fit** — description/name keywords boost models in matching categories

### Frontier vs Non-Frontier

A model is flagged as **frontier** when it meets both of these criteria:
- Provider is a major big-tech company (`openai`, `anthropic`, `google`, `x-ai`, `microsoft`)
- Pricing is expensive: **≥ $1.50 / 1M prompt tokens** or **≥ $8 / 1M completion tokens**

Models that are ultra-expensive (≥ $5 / 1M prompt or ≥ $25 / 1M completion) are always flagged as frontier regardless of provider.

## Running locally

### With Python (requires Python 3.10+)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir .
```

Then open http://localhost:8000

### With Docker

```bash
docker build -t openrouter-top-models .
docker run -p 8000:8000 openrouter-top-models
```

Or use Docker Compose:

```bash
docker compose up --build
```

Then open http://localhost:8000

## API endpoints

- `GET /` — serves the HTML dashboard
- `GET /api/data` — returns JSON with all rankings (cached for 15 minutes)
- `GET /api/health` — health check

## Notes

- Data is fetched from OpenRouter's public Models API and cached in-memory for 15 minutes.
- No OpenRouter API key is required.
- Rankings are heuristic estimates based on metadata. They are **not** official OpenRouter benchmark rankings.
