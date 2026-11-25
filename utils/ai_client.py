"""
================================================================================
 AI CLIENT - THE "PLUG-IN POINT" FOR A REAL AI BRAIN
================================================================================
Right now, this file does NOT call any real AI (no Azure OpenAI, no Gemini).
It uses simple, predictable, rule-based Python logic instead, and every
agent file falls back to that when `ai_client.complete()` returns nothing.

WHY does this file exist on its own, instead of each agent calling an AI
API directly?

Think of it like a single electrical socket in a wall. Every appliance
(every agent) plugs into the SAME socket. Today, nothing is plugged into
the wall behind that socket, so nothing gets power - but the socket
itself, and the wiring to every appliance, is already installed and
working. Later, you just connect the wire behind the socket to a real
power source (a real AI service) and every appliance switches on at
once, with zero rewiring.

That "socket" is the `complete()` method below. Every agent calls it the
same way. Today it always returns None (no AI configured), so every
agent uses its own built-in rule-based logic instead. When you're ready
for Phase 2, you fill in the body of `complete()` and nothing else in
the framework needs to change.
================================================================================
"""
from __future__ import annotations

import os


class AIClient:
    """
    A stand-in for a real AI service.

    HOW TO TURN THIS ON LATER (Phase 2 example, using Azure OpenAI):

        from openai import AzureOpenAI

        def complete(self, system_prompt: str, user_prompt: str) -> str | None:
            if not self.is_configured():
                return None
            client = AzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version="2024-02-01",
            )
            response = client.chat.completions.create(
                model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content

    Until then, `complete()` always returns None, and every agent that
    calls it already knows to fall back to its own rule-based logic.
    That keeps the whole framework 100% runnable today - no API key,
    no cost, no internet dependency.
    """

    def __init__(self):
        # Nothing is configured out of the box. Setting AI_PROVIDER in
        # your .env file (see .env.example) is the switch you flip in
        # Phase 2 - it does nothing by itself until complete() below is
        # filled in.
        self.provider = os.environ.get("AI_PROVIDER", "none")

    def is_configured(self) -> bool:
        return self.provider != "none"

    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        if not self.is_configured():
            return None
        # ---- PHASE 2 PLUG-IN POINT: put your real AI call here ----
        raise NotImplementedError(
            "AI_PROVIDER is set in your .env, but no real AI call is "
            "wired up yet. See the class docstring above this method "
            "for a ready-to-adapt Azure OpenAI example."
        )


# One shared instance every agent imports and calls.
ai_client = AIClient()