"""
OpenRouter Top Models Dashboard
A FastAPI app that fetches models from OpenRouter, ranks them by heuristic scores,
and serves a UI showing top models per category, split by frontier vs non-frontier.
Also integrates real benchmark data from BenchGecko.ai for coding and intelligence rankings.
"""

import asyncio
import difflib
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="OpenRouter Top Models")

# Configuration
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
BENCHGECKO_MODELS_URL = "https://benchgecko.ai/api/v1/models"
CACHE_TTL_SECONDS = 900  # 15 minutes

CATEGORIES = [
    "programming",
    "roleplay",
    "marketing",
    "marketing/seo",
    "technology",
    "science",
    "translation",
    "legal",
    "finance",
    "health",
    "trivia",
    "academia",
]

# "Big tech" providers whose expensive models are considered frontier
FRONTIER_PROVIDERS = {
    "openai",
    "anthropic",
    "google",
    "x-ai",
    "xai",
    "microsoft",
}

# Price threshold in USD per token for a model to be considered "expensive"
EXPENSIVE_PROMPT_THRESHOLD = 0.0000015  # $1.5 per 1M tokens
EXPENSIVE_COMPLETION_THRESHOLD = 0.000008  # $8 per 1M tokens

# BenchGecko coding benchmarks to use for the coding index
CODING_BENCHMARKS = [
    "swe-bench-pro",
    "swe-bench-verified",
    "aa-coding-index",
    "livebench-coding",
    "livebench-agentic-coding",
    "oc-livecodebenchv6",
    "aider-polyglot",
]

# BenchGecko intelligence benchmarks to use for the intelligence index
INTELLIGENCE_BENCHMARKS = [
    "gpqa-diamond",
    "oc-gpqa-diamond",
    "oc-mmlu-pro",
    "helm-mmlu-pro",
    "oc-hle",
    "hle",
    "browsecomp",
    "arc-agi",
    "livebench-reasoning",
]

CATEGORY_PROFILES: dict[str, dict[str, Any]] = {
    "programming": {
        "description": (
            "Programming models are ranked with extra weight on <strong>tool calling</strong> (for building agents and IDE integrations), "
            "<strong>reasoning</strong> (for debugging and algorithm design), <strong>structured outputs / JSON mode</strong> (for generating typed code artefacts), "
            "and <strong>long context windows</strong> (for reading entire codebases). Models whose descriptions mention coding keywords also get a boost. "
            "Value (price per token) is still factored in so affordable workhorses can compete with expensive frontier models."
        ),
        "tools_bonus": 20,
        "reasoning_bonus": 15,
        "structured_outputs_bonus": 12,
        "context_bonus": 12,
        "keyword_bonus": 10,
        "keywords": ("code", "coding", "programming", "developer"),
    },
    "roleplay": {
        "description": (
            "Roleplay models are ranked with heavy emphasis on <strong>very long context windows</strong> (to remember characters, plot threads, and world-building over thousands of tokens). "
            "Models advertised for creative writing, storytelling, or character chat get a strong keyword boost. "
            "Reasoning and tools matter less here, so those bonuses are reduced. Price is still considered so free/cheap creative models can rank highly."
        ),
        "context_bonus": 18,
        "reasoning_bonus": 4,
        "tools_bonus": 3,
        "keyword_bonus": 15,
        "keywords": ("roleplay", "creative", "story", "character", "writing", "fiction"),
    },
    "marketing": {
        "description": (
            "Marketing models are ranked with extra weight on <strong>structured outputs and JSON mode</strong> (for generating ad copy, campaign data, and reports in machine-readable formats), "
            "<strong>reasoning</strong> (for strategy and audience analysis), and <strong>response formatting</strong>. "
            "Models with marketing, SEO, or content-writing keywords in their descriptions get a boost."
        ),
        "structured_outputs_bonus": 14,
        "reasoning_bonus": 8,
        "response_format_bonus": 8,
        "keyword_bonus": 10,
        "keywords": ("marketing", "seo", "content", "writing"),
    },
    "marketing/seo": {
        "description": (
            "Marketing / SEO models are ranked with extra weight on <strong>structured outputs and JSON mode</strong> (for generating ad copy, campaign data, and reports in machine-readable formats), "
            "<strong>reasoning</strong> (for strategy and audience analysis), and <strong>response formatting</strong>. "
            "Models with marketing, SEO, or content-writing keywords in their descriptions get a boost."
        ),
        "structured_outputs_bonus": 14,
        "reasoning_bonus": 8,
        "response_format_bonus": 8,
        "keyword_bonus": 10,
        "keywords": ("marketing", "seo", "content", "writing"),
    },
    "technology": {
        "description": (
            "Technology models are ranked with balanced weighting: <strong>tool calling</strong> and <strong>reasoning</strong> are boosted (for building tech products and troubleshooting), "
            "<strong>context length</strong> matters for reading documentation and logs, and <strong>structured outputs</strong> help with config files and schemas. "
            "Models with technology or IT keywords get a small boost."
        ),
        "tools_bonus": 14,
        "reasoning_bonus": 10,
        "structured_outputs_bonus": 8,
        "context_bonus": 8,
        "keyword_bonus": 8,
        "keywords": ("technology", "tech", "software"),
    },
    "science": {
        "description": (
            "Science models are ranked with heavy weight on <strong>reasoning</strong> (for hypothesis formation and data interpretation), "
            "<strong>long context windows</strong> (for reading research papers and datasets), and <strong>structured outputs</strong> (for producing tables, citations, and reproducible results). "
            "Models described as scientific or research-oriented get a strong keyword boost."
        ),
        "reasoning_bonus": 18,
        "context_bonus": 14,
        "structured_outputs_bonus": 10,
        "keyword_bonus": 10,
        "keywords": ("science", "research", "academic", "technical"),
    },
    "translation": {
        "description": (
            "Translation models are ranked with moderate emphasis on <strong>context length</strong> (to handle full documents rather than sentence fragments) "
            "and models advertised as multilingual or translation-focused get a keyword boost. "
            "Since the OpenRouter API does not explicitly list supported languages, we rely on model descriptions and general capability breadth as proxies."
        ),
        "context_bonus": 10,
        "keyword_bonus": 12,
        "keywords": ("translation", "multilingual", "language"),
    },
    "legal": {
        "description": (
            "Legal models are ranked with extra weight on <strong>reasoning</strong> (for case analysis and contract interpretation), "
            "<strong>very long context windows</strong> (for reading lengthy contracts and case law), and <strong>structured outputs</strong> (for generating clauses, summaries, and formatted briefs). "
            "Models with legal or law keywords get a strong boost."
        ),
        "reasoning_bonus": 15,
        "context_bonus": 14,
        "structured_outputs_bonus": 10,
        "keyword_bonus": 12,
        "keywords": ("legal", "law", "contract"),
    },
    "finance": {
        "description": (
            "Finance models are ranked with extra weight on <strong>reasoning</strong> (for quantitative analysis and risk assessment), "
            "<strong>structured outputs</strong> (for spreadsheets, JSON financial data, and reports), and <strong>context length</strong> (for reading earnings reports and market data). "
            "Models with finance or financial keywords get a boost."
        ),
        "reasoning_bonus": 12,
        "structured_outputs_bonus": 10,
        "context_bonus": 10,
        "keyword_bonus": 10,
        "keywords": ("finance", "financial", "analysis"),
    },
    "health": {
        "description": (
            "Health models are ranked with extra weight on <strong>reasoning</strong> (for differential diagnosis and evidence synthesis), "
            "<strong>long context windows</strong> (for reading medical literature and patient records), and <strong>structured outputs</strong> (for formatted clinical notes and data extraction). "
            "Models with health or medical keywords get a boost."
        ),
        "reasoning_bonus": 12,
        "context_bonus": 10,
        "structured_outputs_bonus": 8,
        "keyword_bonus": 10,
        "keywords": ("health", "medical", "biology"),
    },
    "trivia": {
        "description": (
            "Trivia models are ranked with a balanced, general-purpose scoring profile. "
            "Since trivia benefits from broad knowledge rather than specialised capabilities, we emphasise <strong>overall parameter diversity</strong> (tools, reasoning, structured outputs, vision) "
            "and <strong>value for money</strong> so cheap or free general-knowledge models can shine."
        ),
        "tools_bonus": 10,
        "reasoning_bonus": 8,
        "structured_outputs_bonus": 6,
        "keyword_bonus": 8,
        "keywords": ("knowledge", "trivia", "qa", "question"),
    },
    "academia": {
        "description": (
            "Academia models are ranked similarly to Science: heavy weight on <strong>reasoning</strong> (for critical analysis and literature review), "
            "<strong>very long context windows</strong> (for reading full papers and books), and <strong>structured outputs</strong> (for citations, bibliographies, and formatted research summaries). "
            "Models with academic or research keywords get a strong boost."
        ),
        "reasoning_bonus": 16,
        "context_bonus": 14,
        "structured_outputs_bonus": 10,
        "keyword_bonus": 10,
        "keywords": ("academic", "research", "science", "paper"),
    },
}

BEST_GENERAL_DESCRIPTION = (
    "Best General Models are ranked with a <strong>pure capability-first</strong> approach. "
    "We prioritise models that combine <strong>long context windows</strong>, <strong>multimodal inputs</strong> (vision, audio, video), "
    "<strong>tool calling</strong>, and <strong>reasoning</strong> — the 'full stack' of general-purpose AI. "
    "Cut-down variants (Flash, Lite, Mini, Nano) are <em>penalised</em> so that flagship, fully-capable models rank higher. "
    "Price is deliberately <em>not</em> used as a scoring factor here — this list shows the most capable all-rounders regardless of cost."
)

CODING_BENCHMARKS_DESCRIPTION = (
    "Coding Benchmarks are ranked using <strong>real benchmark scores</strong> from <a href=\"https://benchgecko.ai\" target=\"_blank\" rel=\"noopener\">BenchGecko.ai</a>. "
    "We compute a composite coding index from multiple standardised evaluations: <strong>SWE-bench Pro</strong> (real GitHub issue resolution), "
    "<strong>SWE-bench Verified</strong> (historical software engineering tasks), <strong>LiveCodeBench</strong> (contamination-free competitive programming), "
    "<strong>Aider polyglot</strong> (code editing across languages), and the <strong>Artificial Analysis Coding Index</strong>. "
    "Only models with at least one reported coding benchmark score are included, ranked by their average coding benchmark performance. "
    "Models that appear on OpenRouter but have no published coding benchmark data are not shown here."
)

INTELLIGENCE_BENCHMARKS_DESCRIPTION = (
    "Intelligence Benchmarks are ranked using <strong>real benchmark scores</strong> from <a href=\"https://benchgecko.ai\" target=\"_blank\" rel=\"noopener\">BenchGecko.ai</a>. "
    "We compute a composite intelligence index from multiple standardised evaluations: <strong>GPQA Diamond</strong> (graduate-level reasoning), "
    "<strong>MMLU-Pro</strong> (massive multitask knowledge), <strong>HLE</strong> (hardest language evaluation), "
    "<strong>BrowseComp</strong> (web-based research reasoning), <strong>ARC-AGI</strong> (abstract reasoning), and <strong>LiveBench Reasoning</strong>. "
    "Only models with at least one reported intelligence benchmark score are included, ranked by their average intelligence benchmark performance. "
    "Models that appear on OpenRouter but have no published intelligence benchmark data are not shown here."
)

# In-memory cache
_cache: dict[str, Any] = {}
_last_fetch: float = 0.0
_lock = asyncio.Lock()


def parse_price(val):
    try:
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def is_frontier(model: dict) -> bool:
    """Determine if a model is 'frontier' (expensive big-tech)."""
    provider = model.get("id", "").split("/")[0].lower()
    pricing = model.get("pricing", {})
    prompt_price = parse_price(pricing.get("prompt"))
    completion_price = parse_price(pricing.get("completion"))

    is_big_tech = provider in FRONTIER_PROVIDERS
    is_expensive = prompt_price >= EXPENSIVE_PROMPT_THRESHOLD or completion_price >= EXPENSIVE_COMPLETION_THRESHOLD
    ultra_expensive = prompt_price >= 0.000005 or completion_price >= 0.000025

    return (is_big_tech and is_expensive) or ultra_expensive


def normalise_name(name: str) -> str:
    """Normalise a model name for matching."""
    n = name.lower().strip()
    # Remove provider prefix
    if "/" in n:
        n = n.split("/", 1)[1]
    # Remove common suffixes
    n = re.sub(r"[-:]?(\d{8}|\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}T|\d{4}$|\d{3,4}$)", "", n)
    n = re.sub(r"[:]?free$", "", n)
    n = re.sub(r"[:]?extended$", "", n)
    n = re.sub(r"[:]?thinking$", "", n)
    n = re.sub(r"[:]?nitro$", "", n)
    n = re.sub(r"[:]?online$", "", n)
    n = re.sub(r"[:]?exacto$", "", n)
    n = re.sub(r"[:]?fast$", "", n)
    n = re.sub(r"[:]?max$", "", n)
    n = re.sub(r"[:]?adaptive$", "", n)
    n = re.sub(r"[:]?high$", "", n)
    n = re.sub(r"[:]?preview$", "", n)
    # Clean up punctuation
    n = re.sub(r"[\s\-_]+", " ", n).strip()
    return n


def build_benchgecko_index(benchgecko_models: list[dict]) -> dict[str, dict]:
    """Build a lookup from normalised name to BenchGecko benchmark data."""
    index: dict[str, dict] = {}
    for m in benchgecko_models:
        name = m.get("name", "")
        slug = m.get("slug", "")
        scores = m.get("scores", {})
        normed = normalise_name(name)
        # Also index by slug
        normed_slug = normalise_name(slug.replace("-", " "))
        entry = {
            "name": name,
            "slug": slug,
            "scores": scores,
            "coding_score": _composite_benchmark_score(scores, CODING_BENCHMARKS),
            "intelligence_score": _composite_benchmark_score(scores, INTELLIGENCE_BENCHMARKS),
        }
        if normed:
            index[normed] = entry
        if normed_slug and normed_slug not in index:
            index[normed_slug] = entry
    return index


def _composite_benchmark_score(scores: dict, benchmark_keys: list[str]) -> float | None:
    """Compute average score across a set of benchmark keys."""
    matched = []
    for key in benchmark_keys:
        if key in scores:
            val = scores[key]
            if val is not None and isinstance(val, (int, float)):
                matched.append(float(val))
    if not matched:
        return None
    return round(sum(matched) / len(matched), 2)


def match_benchgecko_to_openrouter(
    openrouter_models: list[dict],
    benchgecko_index: dict[str, dict],
) -> dict[str, dict]:
    """Match OpenRouter models to BenchGecko benchmark data by name similarity."""
    or_names = [normalise_name(m.get("name", "")) for m in openrouter_models]
    bg_names = list(benchgecko_index.keys())

    matched: dict[str, dict] = {}
    for i, or_model in enumerate(openrouter_models):
        or_norm = or_names[i]
        if not or_norm:
            continue

        # Exact match
        if or_norm in benchgecko_index:
            matched[or_model.get("id", "")] = benchgecko_index[or_norm]
            continue

        # Fuzzy match
        ratio, best_idx = 0.0, -1
        for j, bg_name in enumerate(bg_names):
            r = difflib.SequenceMatcher(None, or_norm, bg_name).ratio()
            if r > ratio:
                ratio = r
                best_idx = j

        if ratio > 0.75 and best_idx >= 0:
            matched[or_model.get("id", "")] = benchgecko_index[bg_names[best_idx]]

    return matched


def _base_score(
    model: dict,
    *,
    ctx_weight: float = 25,
    recency_weight: float = 15,
    param_multiplier: float = 1.5,
    tools_bonus: float = 12,
    reasoning_bonus: float = 10,
    structured_outputs_bonus: float = 8,
    response_format_bonus: float = 5,
    vision_bonus: float = 6,
    audio_video_bonus: float = 4,
    context_extra_100k: float = 8,
    context_extra_500k: float = 5,
    max_value_bonus: float = 10,
    keyword_bonus: float = 5,
    keywords: tuple[str, ...] = (),
) -> float:
    """Shared base scoring logic."""
    score = 0.0

    ctx = model.get("context_length") or 0
    if ctx:
        score += min(math.log10(max(ctx, 1)) / math.log10(2_000_000), 1.0) * ctx_weight
        if ctx >= 100_000:
            score += context_extra_100k
        if ctx >= 500_000:
            score += context_extra_500k

    created = model.get("created") or 0
    if created:
        age_days = (time.time() - created) / 86400
        if age_days < 90:
            score += recency_weight
        elif age_days < 180:
            score += recency_weight * 0.67
        elif age_days < 365:
            score += recency_weight * 0.33

    params = model.get("supported_parameters", [])
    param_set = set(params)
    score += len(param_set) * param_multiplier

    if "tools" in param_set:
        score += tools_bonus
    if "reasoning" in param_set or "include_reasoning" in param_set:
        score += reasoning_bonus
    if "structured_outputs" in param_set:
        score += structured_outputs_bonus
    if "response_format" in param_set:
        score += response_format_bonus

    arch = model.get("architecture", {})
    inputs = arch.get("input_modalities", [])
    if "image" in inputs:
        score += vision_bonus
    if "audio" in inputs or "video" in inputs:
        score += audio_video_bonus

    pricing = model.get("pricing", {})
    prompt_price = parse_price(pricing.get("prompt"))
    completion_price = parse_price(pricing.get("completion"))
    avg_price = (prompt_price + completion_price) / 2 if (prompt_price or completion_price) else 0

    if avg_price > 0:
        value_bonus = max(0, max_value_bonus - math.log10(avg_price * 1_000_000 + 1) * 2)
        score += value_bonus
    else:
        score += max_value_bonus * 0.8

    if keywords:
        desc = (model.get("description") or "").lower()
        name = (model.get("name") or "").lower()
        if any(k in desc or k in name for k in keywords):
            score += keyword_bonus

    return score


def score_general_model(model: dict) -> float:
    """Capability-first scoring for 'best general model' ranking."""
    score = _base_score(
        model,
        ctx_weight=30,
        recency_weight=12,
        param_multiplier=1.2,
        tools_bonus=14,
        reasoning_bonus=12,
        structured_outputs_bonus=8,
        response_format_bonus=4,
        vision_bonus=10,
        audio_video_bonus=6,
        context_extra_100k=12,
        context_extra_500k=8,
        max_value_bonus=0,
        keyword_bonus=0,
    )

    ctx = model.get("context_length") or 0
    arch = model.get("architecture", {})
    inputs = arch.get("input_modalities", [])
    params = model.get("supported_parameters", [])
    param_set = set(params)
    has_image = "image" in inputs
    has_text = "text" in inputs

    full_stack_traits = sum([
        ctx >= 100_000,
        has_image and has_text,
        "tools" in param_set,
        "reasoning" in param_set or "include_reasoning" in param_set,
    ])
    if full_stack_traits >= 3:
        score += 18
    elif full_stack_traits >= 2:
        score += 8

    name_lower = (model.get("name") or "").lower()
    if any(k in name_lower for k in ("flash", "lite", "mini", "nano", "tiny")):
        score -= 15

    return round(score, 2)


def score_model(model: dict, category: str | None = None) -> float:
    """Category-aware heuristic score."""
    if category is None:
        return round(_base_score(model), 2)

    profile = CATEGORY_PROFILES.get(category, {})
    score = _base_score(
        model,
        tools_bonus=profile.get("tools_bonus", 12),
        reasoning_bonus=profile.get("reasoning_bonus", 10),
        structured_outputs_bonus=profile.get("structured_outputs_bonus", 8),
        response_format_bonus=profile.get("response_format_bonus", 5),
        context_extra_100k=profile.get("context_bonus", 8),
        context_extra_500k=profile.get("context_bonus", 5) * 0.6 if profile.get("context_bonus") else 5,
        max_value_bonus=10,
        keyword_bonus=profile.get("keyword_bonus", 5),
        keywords=profile.get("keywords", ()),
    )

    return round(score, 2)


def model_family(model: dict) -> str:
    """Return a family key for deduplication (e.g. 'qwen3.5-plus')."""
    slug = model.get("canonical_slug") or model.get("id") or ""
    if "/" in slug:
        slug = slug.split("/", 1)[1]
    slug = re.sub(r"[-:]?(\d{8}|\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}T|\d{4}$|\d{3,4}$)", "", slug)
    slug = re.sub(r"[:]?free$", "", slug)
    slug = re.sub(r"[:]?extended$", "", slug)
    slug = re.sub(r"[:]?thinking$", "", slug)
    slug = re.sub(r"[:]?nitro$", "", slug)
    slug = re.sub(r"[:]?online$", "", slug)
    slug = re.sub(r"[:]?exacto$", "", slug)
    return slug.strip("-").lower()


def deduplicate_top(models: list[dict], n: int = 10) -> list[dict]:
    """Keep top N models, deduplicating by model family."""
    seen: set[str] = set()
    out: list[dict] = []
    for m in models:
        fam = model_family(m)
        if fam in seen:
            continue
        seen.add(fam)
        out.append(m)
        if len(out) >= n:
            break
    return out


def enrich_model(model: dict) -> dict:
    """Add computed fields to a model dict."""
    pricing = model.get("pricing", {})
    prompt_price = parse_price(pricing.get("prompt"))
    completion_price = parse_price(pricing.get("completion"))
    return {
        **model,
        "_frontier": is_frontier(model),
        "_prompt_price_1m": round(prompt_price * 1_000_000, 4),
        "_completion_price_1m": round(completion_price * 1_000_000, 4),
        "_provider": (model.get("id") or "").split("/")[0],
    }


async def fetch_models(client: httpx.AsyncClient, category: str | None = None) -> list[dict]:
    params = {"output_modalities": "text"}
    if category:
        params["category"] = category
    try:
        resp = await client.get(OPENROUTER_MODELS_URL, params=params, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except Exception as e:
        print(f"Error fetching models (category={category}): {e}")
        return []


async def fetch_benchgecko_all(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all models from BenchGecko (paginated)."""
    all_models: list[dict] = []
    page = 1
    while True:
        try:
            resp = await client.get(
                BENCHGECKO_MODELS_URL,
                params={"limit": 200, "page": page},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            all_models.extend(models)
            meta = data.get("meta", {})
            if meta.get("page", 1) >= meta.get("pages", 1):
                break
            page += 1
        except Exception as e:
            print(f"Error fetching BenchGecko page {page}: {e}")
            break
    return all_models


async def build_dashboard_data() -> dict:
    async with httpx.AsyncClient() as client:
        # Fetch all text models from OpenRouter
        all_models = await fetch_models(client)
        all_models = [enrich_model(m) for m in all_models]

        # Fetch benchmark data from BenchGecko
        benchgecko_models = await fetch_benchgecko_all(client)
        bg_index = build_benchgecko_index(benchgecko_models)
        bg_matches = match_benchgecko_to_openrouter(all_models, bg_index)

        # Per-category
        category_tasks = [fetch_models(client, cat) for cat in CATEGORIES]
        category_results = await asyncio.gather(*category_tasks)

    categories_data = {}
    for cat, models in zip(CATEGORIES, category_results):
        enriched = [enrich_model(m) for m in models]
        for m in enriched:
            m["_score"] = score_model(m, category=cat)

        enriched.sort(key=lambda x: x["_score"], reverse=True)

        top_all = deduplicate_top(enriched, n=10)
        non_frontier = [m for m in enriched if not m["_frontier"]]
        top_non_frontier = deduplicate_top(non_frontier, n=10)

        categories_data[cat] = {
            "top": top_all,
            "non_frontier": top_non_frontier,
            "description": CATEGORY_PROFILES.get(cat, {}).get("description", ""),
        }

    # Best general model
    for m in all_models:
        m["_score"] = score_general_model(m)
    all_models.sort(key=lambda x: x["_score"], reverse=True)
    best_general = deduplicate_top(all_models, n=10)

    # Coding benchmarks (from BenchGecko)
    coding_ranked: list[dict] = []
    for m in all_models:
        mid = m.get("id", "")
        bg = bg_matches.get(mid)
        if bg and bg["coding_score"] is not None:
            entry = {**m, "_benchmark_score": bg["coding_score"], "_benchmark_source": "BenchGecko.ai"}
            coding_ranked.append(entry)
    coding_ranked.sort(key=lambda x: x["_benchmark_score"], reverse=True)
    coding_top = deduplicate_top(coding_ranked, n=10)

    # Intelligence benchmarks (from BenchGecko)
    intel_ranked: list[dict] = []
    for m in all_models:
        mid = m.get("id", "")
        bg = bg_matches.get(mid)
        if bg and bg["intelligence_score"] is not None:
            entry = {**m, "_benchmark_score": bg["intelligence_score"], "_benchmark_source": "BenchGecko.ai"}
            intel_ranked.append(entry)
    intel_ranked.sort(key=lambda x: x["_benchmark_score"], reverse=True)
    intel_top = deduplicate_top(intel_ranked, n=10)

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories_data,
        "best_general": best_general,
        "best_general_description": BEST_GENERAL_DESCRIPTION,
        "coding_benchmarks": coding_top,
        "coding_benchmarks_description": CODING_BENCHMARKS_DESCRIPTION,
        "intelligence_benchmarks": intel_top,
        "intelligence_benchmarks_description": INTELLIGENCE_BENCHMARKS_DESCRIPTION,
        "model_count": len(all_models),
        "benchgecko_models_count": len(benchgecko_models),
    }


async def get_data() -> dict:
    global _cache, _last_fetch
    async with _lock:
        now = time.time()
        if _cache and (now - _last_fetch) < CACHE_TTL_SECONDS:
            return _cache
        _cache = await build_dashboard_data()
        _last_fetch = now
        return _cache


@app.get("/api/data")
async def api_data():
    return await get_data()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root():
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
