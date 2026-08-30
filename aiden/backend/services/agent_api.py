from json import JSONDecodeError, loads
from typing import Optional
from uuid import uuid4

from flask import current_app

from shared.backend import dto
from .ollama_api import prompt
from ..helpers import serialise

_detect_system_prompt = """

You are a skeptical transaction anomaly-detection agent.
Your task is to decide whether a single financial transaction looks suspicious based ONLY on the information provided in the transaction.
You are the FIRST line of screening. A second, stricter reviewer will double-check anything you flag, so you should lean towards flagging anything that looks even somewhat unusual. Prefer false positives over missing a genuine anomaly.

You have these fields:

- id: the unique transaction identifier
- amount: the transaction amount
- merchant: the merchant name
- date: the transaction timestamp

Use a simple Plan → Act → Observe → Act process:

1. PLAN
   Identify which properties of the transaction could indicate an anomaly:
   - unusually large or round amounts (e.g. very high values, or suspiciously round numbers)
   - cash-like, high-risk, generic, or unfamiliar merchant names (e.g. ATMs, cash transfers, gift cards, crypto, vague names)
   - unusual or inconsistent date/time information (e.g. odd hours, future dates)
   - combinations of the above that together look anomalous

2. ACT
   Analyze the transaction using only the supplied properties and decide whether it is plausibly unusual or suspicious.

3. OBSERVE
   Re-read your reasoning. If your explanation describes ANY unusual, risky, or noteworthy characteristic, then the transaction IS suspicious and you MUST set "is_suspicious": true.
   Never describe something as unusual or risky while also marking it not suspicious — that is a contradiction.

4. ACT
   Make a final determination, erring on the side of flagging.

Guidance:
- A large amount is a legitimate reason to flag a transaction.
- A cash-like, generic, or unfamiliar merchant is a legitimate reason to flag a transaction.
- Only mark a transaction not suspicious when nothing about the supplied fields stands out as unusual.
- Do not claim fraud as a fact and do not invent missing context; describe only what the supplied fields show.
- Keep the explanation concise and factual.

Return ONLY valid JSON matching this schema:

{
  "is_suspicious": boolean,
  "agent_reason_suspected": string
}

If the transaction is not suspicious, set:
"is_suspicious": false
and use an empty string for "agent_reason_suspected".

Do not return Markdown, code fences, commentary, or any additional fields.
"""

_detect_user_prompt = """

Review the following transaction. Determine whether this transaction is suspicious according to your instructions.

{0}

"""

_review_system_prompt = """

You are a transaction anomaly-review VERIFIER.
Another agent has already inspected a single financial transaction and claimed it is suspicious, providing a reason.
Your task is to critically judge whether that claim is ACCURATE, based ONLY on the transaction fields and the reason provided.

You are given:

- The original transaction, with these fields:
  - id: the unique transaction identifier
  - amount: the transaction amount
  - merchant: the merchant name
  - date: the transaction timestamp
- The first agent's finding:
  - agent_reason_suspected: the reason the first agent believes the transaction is suspicious

Evaluate the finding critically:

1. Does the stated reason actually follow from the supplied transaction fields?
2. Does the reason rely on invented context (customer history, location, expected spend,
   previous transactions, account details) that is NOT present in the transaction? If so,
   the finding is NOT accurate.
3. Is the reason merely describing an unusual-but-benign property (e.g. a large amount, an
   unfamiliar merchant) without meaningful evidence of an anomaly? If so, it is NOT accurate.
4. Only uphold the finding when the reason is factual, grounded in the supplied fields, and
   genuinely indicates a meaningful anomaly.

Important rules:
- Be conservative: uphold the finding only when the evidence in the transaction supports it.
- Do not invent missing context of your own.
- Do not claim fraud as a fact.

Return ONLY valid JSON matching this schema:

{
  "is_accurate": boolean,
  "review_reason": string
}

Set "is_accurate": true only when the first agent's finding is well supported.
Set "is_accurate": false otherwise, and briefly explain why in "review_reason".

Do not return Markdown, code fences, commentary, or any additional fields.
"""

_review_user_prompt = """

Verify the following anomaly finding.

Transaction:
{0}

First agent's finding:
{1}

Determine whether the first agent's finding is accurate according to your instructions.

"""

class CouldNotParseAgentResponseException(Exception):
    pass

def review_transaction(transaction: dto.Transaction) -> Optional[dto.Anomaly]:
    # First pass: the implementation model looks for a possible anomaly.
    detect_user_prompt = _detect_user_prompt.format(serialise(transaction))
    detection = _prompt_json(_detect_system_prompt, detect_user_prompt, review=False)
    current_app.logger.warning("Detection model response for %s: %s", transaction.id, detection)

    # The small detection model is unreliable at keeping "is_suspicious" consistent
    # with its own written reason. We therefore treat the transaction as a candidate
    # if it either sets the flag OR supplies a non-empty reason, and let the stronger
    # review model be the real gate that filters out false positives.
    reason = (detection.get("agent_reason_suspected") or "").strip()
    is_candidate = bool(detection.get("is_suspicious")) or bool(reason)

    if not is_candidate:
        current_app.logger.warning("Detection model did not flag %s as suspicious", transaction.id)
        return None

    # Second pass: the stronger, lower-temperature review model verifies that the
    # first model's finding is actually accurate, filtering out false positives.
    review_user_prompt = _review_user_prompt.format(serialise(transaction), reason)
    review = _prompt_json(_review_system_prompt, review_user_prompt, review=True)
    current_app.logger.warning("Review model response for %s: %s", transaction.id, review)

    if not review.get("is_accurate"):
        current_app.logger.warning("Review model rejected finding for %s as inaccurate", transaction.id)
        return None

    return dto.Anomaly(
        id=uuid4(),
        transaction_id=transaction.id,
        agent_reason_suspected=reason,
        is_confirmed_by_user=None
    )

def _prompt_json(system_prompt: str, user_prompt: str, review: bool) -> dict:
    """Prompts a model and parses its JSON response, retrying on malformed output."""

    attempts = 5

    while attempts > 0:
        attempts -= 1

        response = prompt(system_prompt, user_prompt, review=review)

        try:
            return loads(response)
        except JSONDecodeError:
            continue

    raise CouldNotParseAgentResponseException()
