"""Seed data for a fresh install.

Adding a new built-in provider is mostly a matter of appending a dict here and
(only if the API dialect is new) adding a driver in ``app/providers``.
"""

from __future__ import annotations

from app.config import OLLAMA_DEFAULT_URL

# ---------------------------------------------------------------------------
# Game types
#
# `roles` drives the upload dropdowns and the grouping in the library view.
# Add a type (or edit a role list) and the UI picks it up automatically.
# ---------------------------------------------------------------------------
GAME_TYPES = [
    {
        "id": "rpg",
        "label": "Roleplaying game",
        "description": "Core book, supplements and campaigns.",
        "roles": [
            {"id": "core", "label": "Core rules", "precedence": 0},
            {"id": "errata", "label": "Errata / corrections", "precedence": 100},
            {"id": "expansion", "label": "Supplement / bestiary", "precedence": 0},
            {"id": "campaign", "label": "Campaign", "precedence": 0},
            {"id": "other", "label": "Other", "precedence": 0},
        ],
        "sort_order": 10,
    },
    {
        "id": "boardgame",
        "label": "Board game",
        "description": "Base game, expansions and scenario books.",
        "roles": [
            {"id": "core", "label": "Core rules", "precedence": 0},
            {"id": "errata", "label": "Errata / corrections", "precedence": 100},
            {"id": "expansion", "label": "Expansion", "precedence": 0},
            {"id": "campaign", "label": "Campaign / scenario book", "precedence": 0},
            {"id": "other", "label": "Other", "precedence": 0},
        ],
        "sort_order": 20,
    },
    {
        "id": "wargame",
        "label": "Wargame",
        "description": "Rulebook, army books and campaign supplements.",
        "roles": [
            {"id": "core", "label": "Core rulebook", "precedence": 0},
            {"id": "errata", "label": "Errata / corrections", "precedence": 100},
            {"id": "expansion", "label": "Army book / supplement", "precedence": 0},
            {"id": "campaign", "label": "Campaign", "precedence": 0},
            {"id": "other", "label": "Other", "precedence": 0},
        ],
        "sort_order": 30,
    },
]

# ---------------------------------------------------------------------------
# Built-in AI providers
#
# `kind` selects the driver:
#   openai_compat -> OpenAI, DeepSeek, Qwen, OpenRouter, LM Studio, vLLM, ...
#   anthropic     -> Claude Messages API
#   ollama        -> native Ollama API (chat + embeddings)
# Users can add any number of extra OpenAI-compatible endpoints from the UI.
# ---------------------------------------------------------------------------
BUILTIN_PROVIDERS = [
    {
        "id": "ollama",
        "name": "Ollama (local)",
        "kind": "ollama",
        "base_url": OLLAMA_DEFAULT_URL,
        "chat_model": "",
        "embed_model": "nomic-embed-text",
        "docs_url": "https://ollama.com",
        "description": "Free and local. Point this at a host Ollama, or another machine on your network.",
    },
    {
        "id": "openai",
        "name": "OpenAI (ChatGPT)",
        "kind": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "chat_model": "gpt-4o-mini",
        "embed_model": "text-embedding-3-small",
        "docs_url": "https://platform.openai.com/api-keys",
        "description": "Uses your own API key. Also supports Azure/OpenAI-compatible gateways via a custom provider.",
    },
    {
        "id": "anthropic",
        "name": "Anthropic (Claude)",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "chat_model": "claude-sonnet-4-5",
        "embed_model": "",
        "docs_url": "https://console.anthropic.com/settings/keys",
        "description": "Claude models for answering. Anthropic does not offer an embedding model.",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "kind": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "chat_model": "deepseek-chat",
        "embed_model": "",
        "docs_url": "https://platform.deepseek.com/api_keys",
        "description": "OpenAI-compatible API with competitive pricing.",
    },
    {
        "id": "qwen",
        "name": "Qwen (DashScope)",
        "kind": "openai_compat",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "chat_model": "qwen-plus",
        "embed_model": "text-embedding-v3",
        "docs_url": "https://bailian.console.alibabacloud.com/",
        "description": "Alibaba Cloud Model Studio. Mainland accounts may need the dashscope.aliyuncs.com host.",
    },
]

DEFAULT_SYSTEM_PROMPT = (
    "You are a rules referee for tabletop games. Answer ONLY from the numbered "
    "excerpts. Always establish timing before applying a rule: identify the phase, "
    "step or trigger, what has already happened by then, and whether the card or "
    "effect exists at that point. Setup steps and round phases resolve in printed "
    "order; something introduced after a step cannot be used during it. Respect "
    "when, after, before and Response wording, and if the excerpts do not fix the "
    "order, say so. Excerpts marked ERRATA are official corrections that replace "
    "conflicting core rules: when an errata excerpt conflicts with a core excerpt, "
    "state the errata version as the current rule and do not present the superseded "
    "core version as current. Cite the excerpt number in square brackets after every "
    "statement, for example [3]. Quote exact dice, distances and costs. When a "
    "rule or table gives a formula, do the arithmetic (for example Walk = "
    "Movement x 2, Run = Movement x 4) and state the numbers. When the excerpts "
    "contain comparable entries (other species, weapons, and so on), state the "
    "comparison explicitly with their values. If the "
    "excerpts do not contain the answer, say so plainly and suggest a better search "
    "phrase; never invent rules, page numbers or book names. Do not write a "
    "references or sources list yourself: the application appends one with document "
    "titles, page numbers and links. BGG forum excerpts, when present, are unofficial "
    "community posts; label claims from them as forum opinion and never let them "
    "override a rulebook excerpt."
)
