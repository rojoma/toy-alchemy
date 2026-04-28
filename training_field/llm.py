"""Provider-agnostic LLM wrapper.

Routes chat completions to either OpenAI or Google Gemini based on
per-role environment variables. The rest of the codebase calls
`chat_complete(messages, role="teacher", max_tokens=300)` instead of
constructing a provider client directly.

Configuration (in `.env`):
    # Fallback for any role that doesn't have its own override:
    LLM_MODEL_DEFAULT=openai:gpt-4o

    # Per-role overrides (uppercase ROLE name appended):
    LLM_MODEL_TEACHER=gemini:gemini-3-pro      # cheaper for math-heavy teaching
    LLM_MODEL_STUDENT=openai:gpt-4o
    LLM_MODEL_REFEREE=openai:gpt-4o
    LLM_MODEL_JUDGE=openai:gpt-4o
    LLM_MODEL_QUESTION_BANK=openai:gpt-4o
    LLM_MODEL_TRANSLATOR=openai:gpt-4o
    LLM_MODEL_VISION=openai:gpt-4o             # vision still on OpenAI

Each value is "provider:model_id". Provider must be one of:
    - openai  (uses OPENAI_API_KEY)
    - gemini  (uses GOOGLE_API_KEY)

If `:` is omitted the value is treated as an OpenAI model id.
"""
from __future__ import annotations
import os
from functools import lru_cache
from typing import Optional


def resolve_model_for_role(role: str) -> tuple[str, str]:
    """Return (provider, model_id) for the given role, falling back to
    LLM_MODEL_DEFAULT and finally to openai:gpt-4o."""
    role_env = f"LLM_MODEL_{role.upper()}"
    spec = os.getenv(role_env) or os.getenv("LLM_MODEL_DEFAULT") or "openai:gpt-4o"
    if ":" in spec:
        provider, model_id = spec.split(":", 1)
    else:
        provider, model_id = "openai", spec
    return provider.strip().lower(), model_id.strip()


@lru_cache(maxsize=1)
def _openai_client():
    from openai import OpenAI
    return OpenAI()


@lru_cache(maxsize=1)
def _gemini_client():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY env var is required to use the Gemini provider. "
            "Either set it or change the LLM_MODEL_* env vars to point at OpenAI."
        )
    try:
        from google import genai  # google-genai >= 1.0
    except ImportError as e:
        raise RuntimeError(
            "The google-genai package is not installed. "
            "Run `pip install google-genai` or `pip install -r training_field/requirements.txt`."
        ) from e
    return genai.Client(api_key=api_key)


def chat_complete(
    messages: list[dict],
    *,
    role: str = "default",
    max_tokens: int = 500,
    temperature: Optional[float] = None,
    model_override: Optional[str] = None,
) -> str:
    """Send a chat completion and return the model's text response.

    Args:
        messages: OpenAI-style list of dicts with `role` and `content`.
            role can be "system", "user", or "assistant".
        role: which env-configured model to use, e.g. "teacher", "student",
            "referee", "judge", "question_bank", "translator", "vision".
        max_tokens: cap on output tokens.
        temperature: optional sampling temperature.
        model_override: if given, overrides env config. Format is
            "provider:model_id" (e.g. "gemini:gemini-3-pro") or just an
            OpenAI model id.

    Returns:
        The generated text as a string. Empty string if the model returned
        nothing parseable.
    """
    if model_override:
        if ":" in model_override:
            provider, model_id = model_override.split(":", 1)
        else:
            provider, model_id = "openai", model_override
        provider = provider.strip().lower()
        model_id = model_id.strip()
    else:
        provider, model_id = resolve_model_for_role(role)

    if provider == "openai":
        return _call_openai(messages, model_id, max_tokens, temperature)
    if provider == "gemini":
        return _call_gemini(messages, model_id, max_tokens, temperature)
    raise ValueError(
        f"Unknown LLM provider: {provider!r} (role={role}, model={model_id})"
    )


def _call_openai(messages, model_id, max_tokens, temperature) -> str:
    client = _openai_client()
    kwargs = {"model": model_id, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "")


def _call_gemini(messages, model_id, max_tokens, temperature) -> str:
    """Translate OpenAI-style messages to Gemini's contents and call generate_content."""
    from google.genai import types as gtypes  # type: ignore

    client = _gemini_client()
    system_parts: list[str] = []
    contents: list[dict] = []
    for m in messages:
        msg_role = m.get("role")
        content = m.get("content") or ""
        if not content:
            continue
        if msg_role == "system":
            system_parts.append(content)
        elif msg_role == "user":
            contents.append({"role": "user", "parts": [{"text": content}]})
        elif msg_role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
        # ignore unknown roles silently

    system_instruction = "\n\n".join(system_parts) if system_parts else None

    config_kwargs: dict = {"max_output_tokens": max_tokens}
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    config = gtypes.GenerateContentConfig(**config_kwargs)

    response = client.models.generate_content(
        model=model_id,
        contents=contents,
        config=config,
    )
    # google-genai >=1.x exposes .text as a convenience aggregator.
    text = getattr(response, "text", None)
    if text:
        return text
    # Fallback: walk candidates → content.parts manually for older SDKs.
    parts: list[str] = []
    for cand in getattr(response, "candidates", []) or []:
        content_obj = getattr(cand, "content", None)
        for part in getattr(content_obj, "parts", []) or []:
            t = getattr(part, "text", None)
            if t:
                parts.append(t)
    return "".join(parts)
