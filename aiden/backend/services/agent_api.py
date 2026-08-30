from json import JSONDecodeError, loads
from typing import Optional
from uuid import uuid4

from shared.backend import dto
from .ollama_api import prompt
from ..helpers import serialise

_detect_system_prompt = """

You are a transaction anomaly-review agent.
Your task is to determine whether a single financial transaction appears suspicious based ONLY on the information provided in the transaction.

You have these fields:

- id: the unique transaction identifier
- amount: the transaction amount
- merchant: the merchant name
- date: the transaction timestamp

Use a simple Plan → Act → Observe → Act process:

1. PLAN
   Identify which properties of the transaction could indicate an anomaly:
   - unusually large or small amount
   - unusual merchant characteristics
   - unusual or potentially inconsistent date/time information
   - combinations of the available properties that appear anomalous

2. ACT
   Analyze the transaction using only the supplied properties.
   Consider whether the transaction is plausibly unusual or suspicious.

3. OBSERVE
   Critically inspect your initial conclusion.
   Ask whether the evidence actually supports suspicion, or whether the transaction is merely unusual.
   Do not invent facts about the customer, merchant, location, previous transactions, account history, or expected spending patterns.

4. ACT
   Make a final determination.

A transaction should be marked suspicious only when there is a meaningful reason to believe it is anomalous based on the supplied data.

Important rules:
- Do not claim fraud as a fact.
- Do not invent missing context.
- Do not assume that a high transaction amount is fraudulent.
- Do not assume that an unfamiliar merchant is fraudulent.
- If there is insufficient evidence to identify a meaningful anomaly, classify the transaction as not suspicious.
- Your explanation must describe the evidence that caused the transaction to be considered suspicious.
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

    if not detection.get("is_suspicious"):
        return None

    reason = detection.get("agent_reason_suspected", "")

    # Second pass: the stronger, lower-temperature review model verifies that the
    # first model's finding is actually accurate, filtering out false positives.
    review_user_prompt = _review_user_prompt.format(serialise(transaction), reason)
    review = _prompt_json(_review_system_prompt, review_user_prompt, review=True)

    if not review.get("is_accurate"):
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
