"""
LLM Provider abstraction for the AML pipeline
=============================================

Refactor target: gives "data sovereignty" a concrete, demonstrable shape.

Agents 2 (extraction) and 4 (reporting) previously constructed a hard-coded
cloud model (ChatGoogleGenerativeAI / ChatAnthropic) inline. That design
silently locked every trust-deed document (client PII) into Google and
Anthropic's clouds — the project name "Sovereign AML" was aspirational.

This module introduces a small ``LLMProvider`` protocol with two call
shapes that map exactly onto the pipeline's two generative agents:

    * ``extract_structured(...)``   -> Agent 2, one best-effort structured
                                       extraction (feed one chunk, get a
                                       pydantic object back).
    * ``generate_text(...)``        -> Agent 4, free-form text (audit memo).

Two implementations ship with it:

    * ``CloudLLMProvider``  — the default. Wraps the existing Gemini /
      Claude calls through langchain, preserving current behaviour bit-for-bit.
    * ``OllamaLLMProvider`` — a local second implementation that talks to an
      Ollama endpoint through its OpenAI-compatible API (plain ``requests``,
      no vendor SDK). The local open-weight model will be *worse* at
      extraction for now — that is fine. The point of the stub is not "local
      is as good as Gemini", it is: *the architecture does not force you to
      send client PII into a foreign cloud, and here is a working seam to
      prove it.*

Provider selection is an **admin-configured deployment decision** (env var),
never a per-request user choice — consistent with ADR-001's argument that
model choice in a compliance pipeline is a governed decision, not a
preference.

Selection (env):

    LLM_PROVIDER     = "cloud" (default) | "ollama"
    OLLAMA_BASE_URL  = "http://localhost:11434"   (ollama provider)
    OLLAMA_MODEL     = e.g. "qwen2.5:7b"          (ollama provider)

Ollama context window (READ THIS before running the ollama path)
---------------------------------------------------------------
The pipeline chunks documents at CHUNK_SIZE = 60_000 characters — roughly
15,000+ tokens per chunk once the system prompt and structured-output schema
are added. Ollama's default context window is only 4,096 tokens, and the
OpenAI-compatible endpoint this provider calls (``/v1/chat/completions``)
*has no way to raise it per-request*: ``num_ctx`` is not part of the OpenAI
request schema, so it can only be set server-side.

Worse, when input exceeds the active context window Ollama does **not** error
— it silently truncates from the beginning of the prompt, with no warning in
the response. For a compliance pipeline that is a quiet data-loss bug: a chunk
containing beneficiaries A, B and C can be truncated down to just C, produce a
still-valid ``TrustDeedExtraction`` (this provider's fallback is deliberately
non-raising), and nothing downstream learns that two beneficiaries were
dropped.

So anyone running the Ollama path MUST size the model's context to at least
the chunk size, either by:

    * setting ``OLLAMA_CONTEXT_LENGTH`` on the Ollama server for every model
      used by this pipeline, or
    * ``ollama create <name> -f Modelfile`` with ``PARAMETER num_ctx <n>``
      baked into a custom model, where ``<n>`` covers your CHUNK_SIZE.

At startup this provider calls ``/api/show`` and loudly warns (or refuses to
start, with ``OLLAMA_REQUIRE_CONTEXT=true``) if the model's active context is
smaller than the required size — turning the silent truncation into a visible
failure instead.

Additional ollama env knobs:

    OLLAMA_MIN_CONTEXT        = required active context in tokens
                                (default derived from CHUNK_SIZE estimate)
    OLLAMA_REQUIRE_CONTEXT    = "true" to refuse to start when the check fails
                                (default: log a loud warning and continue)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import requests

if TYPE_CHECKING:
    from pydantic import BaseModel

log = logging.getLogger("llm_provider")


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal seam every generative agent call passes through."""

    @property
    def name(self) -> str:
        ...

    def extract_structured(self, *, prompt: str, output_schema: type) -> object:
        """One structured extraction. Returns an instance of ``output_schema``.

        Implementations should never raise on a poor model response; they
        return a schema-shaped object (best-effort) so that Agent 3 can always
        run. This mirrors how Agent 2 already tolerates per-chunk failures.
        """
        ...

    def generate_text(self, *, prompt: str) -> str:
        """Free-form text generation (Agent 4 audit memo). Returns plain text."""
        ...


class CloudLLMProvider:
    """Default provider. Wraps the established Gemini + Claude langchain calls.

    This is the exact behaviour the pipeline had before the refactor, so
    switching the default to ``cloud`` is a strict no-op for existing flows.
    """

    def __init__(
        self,
        *,
        extraction_model: str | None = None,
        report_model: str | None = None,
    ) -> None:
        self._extraction_model = extraction_model or os.environ.get(
            "EXTRACTION_MODEL", "gemini-3.1-pro-preview"
        )
        self._report_model = report_model or os.environ.get(
            "REPORT_MODEL", "claude-sonnet-5"
        )
        self._structured_llm_cache: dict[type, object] = {}

    @property
    def name(self) -> str:
        return "cloud"

    def _structured_extractor(self, output_schema: type):
        if output_schema not in self._structured_llm_cache:
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model=self._extraction_model,
                temperature=0,
                api_key=os.environ["GOOGLE_API_KEY"],
            )
            self._structured_llm_cache[output_schema] = llm.with_structured_output(
                output_schema
            )
        return self._structured_llm_cache[output_schema]

    def extract_structured(self, *, prompt: str, output_schema: type) -> object:
        return self._structured_extractor(output_schema).invoke(prompt)

    def generate_text(self, *, prompt: str) -> str:
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model=self._report_model,
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
        response = llm.invoke(prompt)
        return _flatten_content(response.content)


class OllamaLLMProvider:
    """Local-provider stub: speaks Ollama's OpenAI-compatible chat API.

    Uses only ``requests`` — no vendor SDK — so adding or replacing a local
    model never touches the pipeline. Extraction here is best-effort JSON;
    quality will trail a frontier cloud model, and that trade-off is exactly
    what data sovereignty is about. See the module docstring for the mandatory
    context-window sizing — Ollama silently truncates over-length input, so a
    startup sanity check runs here rather than letting that manifest as a
    silent compliance gap.
    """

    # Default required active context (tokens). Mirrors the pipeline's
    # CHUNK_SIZE=60_000 chars → ~15,000 tokens, plus headroom for the system
    # prompt and structured-output schema. OLLAMA_MIN_CONTEXT overrides it.
    _DEFAULT_REQUIRED_CONTEXT = 24_000

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        min_context: int | None = None,
        require_context: bool = False,
    ) -> None:
        self._base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self._model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        self._min_context = min_context or int(
            os.environ.get("OLLAMA_MIN_CONTEXT", self._DEFAULT_REQUIRED_CONTEXT)
        )
        self._require_context = require_context or os.environ.get(
            "OLLAMA_REQUIRE_CONTEXT", "false"
        ).strip().lower() == "true"
        # Fail fast on a misconfigured context window before any document is
        # screened — a silent truncation here is a compliance gap, so surface
        # it as a loud, visible startup problem instead.
        self._check_context_length()

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"

    def _check_context_length(self) -> None:
        """Warn loudly (or refuse to start) if the model's active context is too small.

        Queries ``/api/show`` for the configured model's active context length
        and compares it against the required minimum. If the server can't be
        reached, we log a warning and continue so the provider can still be
        exercised serverless (tests, dry runs); the check is about catching a
        *reachable-but-undersized* deployment, which is exactly the silent
        truncation hazard.
        """
        try:
            resp = requests.post(
                f"{self._base_url}/api/show",
                json={"model": self._model},
                timeout=30,
            )
            resp.raise_for_status()
            model_info = resp.json()
        except Exception as exc:  # noqa: BLE001 - host may be down; don't block
            log.warning(
                "ollama: could not verify context length for %s (%s); "
                "proceeding without the startup check. Set OLLAMA_CONTEXT_LENGTH "
                "or PARAMETER num_ctx to >= %d tokens or input will be silently "
                "truncated.",
                self._model, exc, self._min_context,
            )
            return

        active = self._active_context(
            model_info.get("model_info") or {}, model_info.get("parameters") or ""
        )
        if active is None:
            log.warning(
                "ollama: could not determine active context length for %s from "
                "/api/show; if it is < %d tokens, over-length chunks will be "
                "silently truncated.",
                self._model, self._min_context,
            )
            return

        if active < self._min_context:
            msg = (
                f"ollama: model {self._model} active context is {active} tokens, "
                f"below the required {self._min_context} (pipeline CHUNK_SIZE). "
                f"Chunks exceeding the window are SILENTLY TRUNCATED — set "
                f"OLLAMA_CONTEXT_LENGTH on the server or bake PARAMETER num_ctx "
                f"{self._min_context} into a custom Modelfile."
            )
            if self._require_context:
                raise RuntimeError(msg)
            log.error(msg)
        else:
            log.info(
                "ollama: model %s active context %d tokens meets the required %d.",
                self._model, active, self._min_context,
            )

    @staticmethod
    def _active_context(model_info: dict, parameters: str) -> int | None:
        """Best-effort read of the model's *active* context length (tokens).

        Checks the resolved ``model_info`` first (authoritative for a running
        model regardless of where num_ctx was set), then falls back to the raw
        Modelfile ``parameters`` string.
        """
        for key in ("llama.context_length", "context_length", "num_ctx"):
            val = model_info.get(key)
            if isinstance(val, (int, float)):
                return int(val)
            if isinstance(val, str) and val.strip().isdigit():
                return int(val)
        # parameters is a Modelfile text block, e.g. 'num_ctx 8192\n...'
        m = re.search(r"(?m)^\s*num_ctx\s+(\d+)\s*$", parameters)
        if m:
            return int(m.group(1))
        return None

    def _chat(self, prompt: str, *, system: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "temperature": 0,
        }
        resp = requests.post(
            f"{self._base_url}/v1/chat/completions",
            json=payload,
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def extract_structured(self, *, prompt: str, output_schema: type) -> object:
        system = (
            "You are an expert Australian AML/KYC compliance analyst. "
            "Respond with ONLY a single valid JSON object matching this schema. "
            f"JSON schema: {output_schema.model_json_schema()}"
        )
        try:
            raw = self._chat(prompt, system=system)
            obj = _extract_json_object(raw)
            return output_schema.model_validate(obj)
        except Exception as exc:  # noqa: BLE001 - best-effort, never block Agent 3
            log.warning(
                "ollama: structured extraction failed (%s); returning empty schema", exc
            )
            return output_schema()

    def generate_text(self, *, prompt: str) -> str:
        system = "You are the Lead Compliance Writer for an Australian Financial Institution."
        return self._chat(prompt, system=system)


def get_provider() -> LLMProvider:
    """Factory: resolve the configured provider once per process.

    Selection is an admin-configured deployment decision via ``LLM_PROVIDER``,
    never a per-request user choice. Defaults to ``cloud`` so existing
    behaviour is unchanged unless explicitly opted into a local model.
    """
    kind = os.environ.get("LLM_PROVIDER", "cloud").strip().lower()
    if kind == "ollama":
        log.info("LLM provider: ollama (local inference, data stays in-house)")
        return OllamaLLMProvider()
    log.info(
        "LLM provider: cloud (Gemini extraction / Claude reporting) — "
        "set LLM_PROVIDER=ollama for a self-hosted option"
    )
    return CloudLLMProvider()


def _flatten_content(content) -> str:
    """Collapse a langchain/anthropic content payload into plain text.

    Handles both plain strings (older SDKs) and Claude's list-of-block form,
    skipping internal ``thinking`` blocks so they never leak into the memo.
    """
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "thinking":
                continue
            parts.append(block.get("text") or "")
        elif hasattr(block, "type") and getattr(block, "type", None) == "thinking":
            continue
        else:
            parts.append(str(getattr(block, "text", block) or ""))
    return "\n".join(p for p in parts if p)


def _extract_json_object(raw: str) -> dict:
    """Best-effort lift of the first JSON object out of a model's reply.

    Tolerates models that wrap JSON in prose or code fences.
    """
    cleaned = raw.strip()
    # Strip a surrounding code fence if present.
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        # drop the trailing ```  fence line
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} span.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError("No JSON object found in model response")
