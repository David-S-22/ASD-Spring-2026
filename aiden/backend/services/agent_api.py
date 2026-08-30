from json import JSONDecodeError, loads
from typing import Optional
from uuid import uuid4

from shared.backend import dto
from .ollama_api import prompt
from ..helpers import serialise

_system_prompt = """

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

_user_prompt = """

Review the following transaction. Determine whether this transaction is suspicious according to your instructions.

{0}

"""

class CouldNotParseAgentResponseException(Exception):
    pass

def review_transaction(transaction: dto.Transaction) -> Optional[dto.Anomaly]:
    attempts = 5

    while attempts > 0:
        attempts -= 1

        user_prompt = _user_prompt.format(serialise(transaction))
        response = prompt(_system_prompt, user_prompt)

        try:
            obj = loads(response)
        except JSONDecodeError:
            continue

    if attempts == 0:
        raise CouldNotParseAgentResponseException()

    if not obj["is_suspicious"]:
        return None

    return dto.Anomaly(
        id=uuid4(),
        transaction_id=transaction.id,
        agent_reason_suspected=obj["agent_reason_suspected"],
        is_confirmed_by_user=None
    )
