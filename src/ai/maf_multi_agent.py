"""
Multi-Agent Orchestrator for Cortex IDE (Provider-Native).

Replaces the non-functional CoordinationEngine with real multi-agent
orchestration using Cortex's own LLM providers (Kimi, DeepSeek, Mistral, OpenAI).

Architecture (when autogen toggle is ON):
  1. Planner Agent  – breaks the coding task into a numbered step plan
  2. Executor Agent – the existing Cortex agent_bridge tool loop (unchanged)
  3. Reviewer Agent – reviews the completed work against the plan

The Planner and Reviewer are pure LLM calls (no tools) that use Cortex's
existing BaseProvider subclasses which correctly call /v1/chat/completions.
MAF's OpenAIChatClient was removed because it hardcodes /v1/responses
(OpenAI Responses API), which Kimi/DeepSeek/Mistral don't support.

Usage:
    from src.ai.providers import get_provider_registry, ProviderType, ChatMessage
    registry = get_provider_registry()
    provider = registry.get_provider(ProviderType.KIMI)
    orchestrator = MafMultiAgentOrchestrator(provider, model_id="kimi-k2.6")
    plan = orchestrator.run_planner("Add 3D scroll effects to index.html")
    # ... run Cortex agent_bridge with plan as context ...
    review = orchestrator.run_reviewer(plan, executor_output)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger("maf_multi_agent")


# ── Provider endpoint mapping (for external lookup) ───────────────────
PROVIDER_BASE_URLS: Dict[str, str] = {
    "kimi":      "https://api.moonshot.ai/v1",
    "deepseek":  "https://api.deepseek.com/v1",
    "mistral":   "https://api.mistral.ai/v1",
    "codestral": "https://api.mistral.ai/v1",
    "openai":    "https://api.openai.com/v1",
}

PROVIDER_ENV_KEY_MAP: Dict[str, str] = {
    "kimi":      "MOONSHOT_API_KEY",
    "deepseek":  "DEEPSEEK_API_KEY",
    "mistral":   "MISTRAL_API_KEY",
    "codestral": "MISTRAL_API_KEY",
    "openai":    "OPENAI_API_KEY",
}

# ── Agent system prompts ──────────────────────────────────────────────

PLANNER_INSTRUCTIONS = """You are a task planner for a coding AI assistant.
Given a user's coding or software-engineering request, produce a concise,
numbered, step-by-step implementation plan.

Rules:
- Output ONLY the plan. No greetings, no explanations, no markdown headings.
- Each step must be a single, actionable sentence.
- Keep the plan to 3-7 steps.
- Focus on what files to create/modify and in what order.
- If the request is simple (e.g. a question), output "Direct answer — no plan needed."

Example:
1. Read index.html to understand current structure.
2. Add CSS 3D perspective and preserve-3d to the scroll container.
3. Add JavaScript parallax tilt on mousemove.
4. Add Three.js canvas for floating geometric accents.
5. Test scroll behavior and adjust z-index layering."""

REVIEWER_INSTRUCTIONS_TEMPLATE = """You are a code reviewer.  The user asked:
"{user_request}"

The implementation plan was:
{plan_text}

Below is a summary of what the coding agent did.  Your job is to review
the completed work against the plan and identify any gaps, bugs, or
improvement opportunities.

Rules:
- Be concise — output 1-4 bullet points.
- If everything looks good, say "All plan steps completed successfully."
- Flag ONLY real issues (missing steps, potential bugs, edge cases).
- Do NOT repeat the plan or the completed work verbatim."""


class MafMultiAgentOrchestrator:
    """Multi-agent orchestrator using Cortex's native LLM providers.

    Provides Planner → Executor → Reviewer pipeline when the autogen
    multi-agent toggle is ON in the Cortex chat UI.

    Uses Cortex's BaseProvider subclasses (KimiProvider, DeepSeekProvider,
    MistralProvider) which correctly call /v1/chat/completions — avoiding
    the MAF OpenAIChatClient's hardcoded /v1/responses incompatibility.
    """

    def __init__(
        self,
        provider: Any,  # BaseProvider subclass instance
        model_id: str = "",
        provider_name: str = "",
    ):
        """Initialize the orchestrator with a Cortex provider instance.

        Args:
            provider:      A BaseProvider instance (KimiProvider, etc.).
            model_id:      LLM model ID (e.g. "kimi-k2.6", "deepseek-v4-pro").
            provider_name: "kimi", "deepseek", "mistral", "codestral", "openai".
        """
        self._provider = provider
        self.model_id = model_id or getattr(provider, 'available_models', lambda: [type('M', (), {'id': 'unknown'})])()[0].id  # type: ignore[union-attr]
        self.provider_name = provider_name.lower() if provider_name else ""
        self._cancelled = False

        log.info(
            "[MAF] Orchestrator init: model=%s provider=%s",
            self.model_id, self.provider_name or "custom",
        )

    # ── Chat helper ───────────────────────────────────────────────────

    def _chat(self, messages: List[Dict[str, str]], max_tokens: int = 4096) -> str:
        """Send a chat completion through the Cortex provider.

        Returns the response text, or empty string on failure.
        """
        if self._cancelled:
            return ""

        # Import here to avoid circular imports at module level
        from src.ai.providers import ChatMessage

        cortex_messages = [
            ChatMessage(role=m["role"], content=m["content"])
            for m in messages
        ]

        try:
            response = self._provider.chat(
                messages=cortex_messages,
                model=self.model_id,
                temperature=1.0,   # Kimi requires 1.0; safe for others
                max_tokens=max_tokens,
                stream=False,
            )
            if response.error:
                log.error("[MAF] Provider error: %s", response.error)
                return ""
            return (response.content or "").strip()
        except Exception as exc:
            log.error("[MAF] Chat call failed: %s", exc, exc_info=True)
            return ""

    # ── Planner ───────────────────────────────────────────────────────

    def run_planner(self, user_message: str) -> str:
        """Run the Planner.

        Returns a step-by-step implementation plan as a plain-text string,
        or an empty string if the planner is not needed for simple queries.
        """
        if self._cancelled:
            return ""

        log.info("[MAF] Planner running for: %.80s", user_message)
        messages = [
            {"role": "system", "content": PLANNER_INSTRUCTIONS},
            {"role": "user", "content": user_message},
        ]
        try:
            plan_text = self._chat(messages, max_tokens=2048)
            if not plan_text:
                return ""

            # Detect "no plan needed" responses
            if "no plan needed" in plan_text.lower():
                log.info("[MAF] Planner: no plan needed (simple query)")
                return ""

            log.info("[MAF] Planner output: %d chars", len(plan_text))
            return plan_text
        except Exception as exc:
            log.error("[MAF] Planner failed: %s", exc, exc_info=True)
            return ""  # Graceful fallback — proceed without plan

    # ── Reviewer ──────────────────────────────────────────────────────

    def run_reviewer(
        self,
        user_request: str,
        plan_text: str,
        executor_output: str,
    ) -> str:
        """Run the Reviewer.

        Args:
            user_request:    Original user message.
            plan_text:       Planner output (may be empty).
            executor_output: Summary of what the coding agent did.

        Returns a concise review (1-4 bullet points) or empty string on failure.
        """
        if self._cancelled:
            return ""

        instructions = REVIEWER_INSTRUCTIONS_TEMPLATE.format(
            user_request=user_request,
            plan_text=plan_text or "(no plan — direct execution)",
        )

        log.info("[MAF] Reviewer running — plan=%d chars, output=%d chars",
                 len(plan_text), len(executor_output))
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": executor_output},
        ]
        try:
            review_text = self._chat(messages, max_tokens=1024)
            if review_text:
                log.info("[MAF] Reviewer output: %d chars", len(review_text))
            return review_text
        except Exception as exc:
            log.error("[MAF] Reviewer failed: %s", exc, exc_info=True)
            return ""

    # ── Cancel ────────────────────────────────────────────────────────

    def cancel(self):
        """Cancel any in-progress MAF operations."""
        self._cancelled = True
        log.info("[MAF] Orchestrator cancelled")

    # ── Static helpers ────────────────────────────────────────────────

    @staticmethod
    def resolve_api_key(provider_name: str) -> str:
        """Look up the API key for a provider from environment variables.

        Args:
            provider_name: "kimi", "deepseek", "mistral", "codestral", "openai".

        Returns the API key string, or empty string if not configured.
        """
        env_key = PROVIDER_ENV_KEY_MAP.get(provider_name.lower(), "")
        return os.getenv(env_key, "") if env_key else ""

    @staticmethod
    def resolve_base_url(provider_name: str) -> str:
        """Look up the base URL for a provider."""
        return PROVIDER_BASE_URLS.get(provider_name.lower(), "https://api.openai.com/v1")
