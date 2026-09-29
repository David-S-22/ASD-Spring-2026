"""Prompt and fallback for grounded answers about the user's bills (sources come from retrieve_context)."""

SYSTEM = (
    "You are Tally, answering one question about the user's bills. Use ONLY the sources listed below; "
    "never invent a bill, an amount or a date, and never add amounts up. "
    'Respond with JSON only, exactly these keys: {"answer": "<string, at most 60 words>", '
    '"cited": [<the source file names you used, copied exactly>], '
    '"insufficient": <true when the sources do not cover the question>}. '
    'When insufficient is true, "cited" must be [] and "answer" must be "".'
)

FALLBACK = {"answer": "", "cited": [], "insufficient": True}


def _source_block(chunks):
    """One "- [Source: file]: text" line per chunk, whitespace collapsed."""
    return "\n".join(f"- [Source: {chunk['source']}]: {' '.join(chunk['text'].split())}" for chunk in chunks)


def build(question, chunks, error=None):
    """Return the chat messages: system rules plus sources, then the question, then the retry note if any."""
    messages = [
        {"role": "system", "content": f"{SYSTEM}\nSources:\n{_source_block(chunks)}"},
        {"role": "user", "content": question},
    ]
    if error:
        messages.append({"role": "user", "content": f"Your last response was invalid: {error}. Reply again, JSON only."})
    return messages
