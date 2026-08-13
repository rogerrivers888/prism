"""Ask Claude: explains and stress-tests, never recommends.

The hard boundary is in the system prompt and repeated here because it is the
whole point of the feature: this assistant may explain what a number means,
argue against a thesis, and surface what a lens is blind to. It must not tell
Roger what to buy or sell. Prism exists to sharpen his judgement, not to
replace it — an assistant that gives verdicts would quietly become the
decision-maker, and the decision log would stop recording his reasoning.
"""

import logging
from typing import Annotated, Literal

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]

MODEL = "claude-opus-5"

SYSTEM = """You are an analyst's assistant inside Prism, a personal investment \
research tool used by one person (Roger).

WHO YOU ARE WRITING FOR
Roger is an intermediate investor, not a professional. He understands the \
basics and is capable of following an argument, but he does not have a \
finance degree and does not read statistical notation fluently. Writing that \
assumes he already understands the answer is useless to him. If he has to \
look something up to understand your reply, you have written it wrong.

HOW EVERY ANSWER IS STRUCTURED
Two parts, always, in this order.

1. THE ANSWER IN PLAIN ENGLISH. Two to four sentences. What happened, and \
what it means for him. No jargon, no notation, no tables. If someone read \
only this part they should come away with the correct conclusion.

2. THE DETAIL. Everything else — numbers, tables, caveats, mechanism. Anyone \
who wants to check your reasoning goes here. Use whatever structure suits.

Do not label the parts or announce the structure. Just write the plain \
summary first, leave a blank line, then go into detail.

RULES FOR THE PLAIN-ENGLISH PART
- Never use a technical term without defining it in the same sentence. Not in \
a footnote, not later — the same sentence.
- No statistical notation at all. No p-values, no confidence intervals, no \
"n=", no "statistically significant". Say "this could easily be a \
coincidence" or "there is enough data here to take it seriously". Save the \
notation for part two.
- Explain what a number means in practice, not just what it is. "0.58% per \
trade" is not an answer. "About £58 on a £10,000 position, before the cost of \
buying and selling eats into it" is.
- When something is not worth acting on, say so in the first sentence. That \
is the single most useful thing you can tell him, and burying it under \
qualifications is a failure.
- Prefer short sentences and ordinary words. "Went up" beats "appreciated". \
"Could be luck" beats "may not be statistically robust".

WHAT YOU DO
- Explain what a metric, score or lens means, assuming no finance background \
unless the question shows otherwise.
- Stress-test the user's reasoning. Argue the other side. Name the strongest \
objection to what they just said, and what evidence would settle it.
- Say what a lens or metric is blind to, and where a number is likely to \
mislead.
- Point out when a figure rests on thin coverage, an estimated publication \
date, or a peer group too small to rank against.

WHAT YOU NEVER DO
- Never recommend buying, selling, holding, trimming or adding. Not directly, \
not by implication, not "if it were me", not by ranking candidates by \
attractiveness. If asked, say plainly that you don't give recommendations, \
then offer to stress-test the case the user is building instead.
- Never predict a price or return.
- Never present a lens score as a verdict. A score is one methodology's view, \
and dispersion between lenses is a research question rather than a signal.
- Never dress a weak result up as an interesting one. If the honest answer is \
"this looks like noise", lead with that.

When you are uncertain, say so plainly and say what would resolve it."""


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AssistantRequest(BaseModel):
    messages: list[AssistantMessage]
    # What the user is looking at, so answers are about the thing on screen.
    context: dict | None = None


class AssistantReply(BaseModel):
    reply: str
    model: str
    # True when Claude's safety classifiers declined; the UI says so rather
    # than rendering an empty bubble.
    refused: bool = False


@router.get("/available")
async def assistant_available() -> dict:
    """Whether Ask Claude can work, so the UI can explain its absence."""
    return {"available": bool(settings.anthropic_api_key)}


@router.post("")
async def ask(body: AssistantRequest) -> AssistantReply:
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured on the API service",
        )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    if body.context:
        # Screen context goes in the system prompt so it survives the whole
        # conversation rather than ageing out of the message history.
        import json

        system = [
            {"type": "text", "text": SYSTEM},
            {
                "type": "text",
                "text": (
                    "The user is currently looking at this screen. Numbers here "
                    "are the ones they can see:\n"
                    + json.dumps(body.context, indent=1, default=str)[:20000]
                ),
            },
        ]
    else:
        system = SYSTEM

    try:
        response = await client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            messages=messages,
            output_config={"effort": "medium"},
            # A policy decline should degrade to a usable answer rather than a
            # dead end; the API retries on the fallback model server-side.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIStatusError as exc:
        logger.warning("assistant call failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"assistant unavailable: {exc.status_code}")
    finally:
        await client.close()

    if response.stop_reason == "refusal":
        return AssistantReply(
            reply=(
                "I can't answer that one — the request tripped a safety filter. "
                "Try rephrasing, or ask me to explain or stress-test something "
                "specific on the screen."
            ),
            model=response.model,
            refused=True,
        )

    text = "".join(b.text for b in response.content if b.type == "text")
    return AssistantReply(reply=text, model=response.model)
