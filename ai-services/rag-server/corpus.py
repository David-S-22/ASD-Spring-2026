"""Where the knowledge comes from. Finds every feature loader in sources/, runs it, and checks
the chunks it returns. Also the shared extractors loaders can call (doc_chunks). Chroma does the
storing, embedding and searching — nothing in here touches vectors."""
import importlib
import pkgutil
import re
from pathlib import Path

import sources

# A chunk is {"id": str, "text": str, "metadata": {...}}. metadata is a flat dict of
# str/int/float/bool values — whatever the loader can extract — and MUST include:
#   feature   the loader's feature name, lowercase             "bills"
#   tier      1 = a database row (fact), 2 = an approved doc
# Everything else is up to the loader and comes back on every citation, e.g.
#   record, record_id, bill_id, date, status      for rows
#   doc, section, part                            for documents (doc_chunks adds these)
#   label                                          a short human name for the UI chip
REQUIRED_META = ("feature", "tier")


def features():
    """Names of every loader in sources/ (files starting with _ are skipped)."""
    return sorted(m.name for m in pkgutil.iter_modules(sources.__path__) if not m.name.startswith("_"))


def load(feature):
    """Run one feature's loader and validate its chunks. Raises on any problem."""
    module = importlib.import_module(f"sources.{feature}")
    chunks = module.load_chunks()
    seen = set()
    for c in chunks:
        if not c.get("id") or not c.get("text"):
            raise ValueError(f"chunk without id or text: {c!r:.80}")
        if c["id"] in seen:
            raise ValueError(f"duplicate chunk id {c['id']}")
        seen.add(c["id"])
        meta = c.get("metadata") or {}
        for key in REQUIRED_META:
            if key not in meta:
                raise ValueError(f"chunk {c['id']} metadata is missing {key!r}")
        if meta["feature"] != feature:
            raise ValueError(f"chunk {c['id']} says feature={meta['feature']!r} but lives in sources/{feature}.py")
        bad = {k: v for k, v in meta.items() if not isinstance(v, (str, int, float, bool))}
        if bad:
            raise ValueError(f"chunk {c['id']} metadata must be str/int/float/bool, got {bad}")
    return chunks


def benchmarks(feature):
    """The feature's BENCHMARKS list (eval.py and the agentic loop run these)."""
    return getattr(importlib.import_module(f"sources.{feature}"), "BENCHMARKS", [])


# --- shared extractors ----------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def doc_chunks(path, feature, words=80, tier=2, min_words=8, **extra):
    """Cut one markdown file into ~`words`-word pieces that never cross a heading, and extract
    the metadata a citation needs: doc (file name), section (nearest heading), part (piece number
    within that section). Pieces shorter than `min_words` (a heading with a one-line body) are
    dropped so they can't be retrieved as "evidence". Skips silently if the file is missing so a
    moved doc never breaks refresh."""
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    sections, last, title = [], 0, ""
    for m in _HEADING.finditer(text):
        sections.append((title, text[last:m.start()]))
        title, last = m.group(2).strip(), m.end()
    sections.append((title, text[last:]))

    chunks, n = [], 0
    for section, body in sections:
        toks = body.split()
        for part, start in enumerate(range(0, len(toks), words), start=1):
            piece_toks = toks[start:start + words]
            if len(piece_toks) < min_words:
                continue
            n += 1
            piece = " ".join(piece_toks)
            chunks.append({
                "id": f"{feature}:docs/{path.name}#{n}",
                "text": (f"{section}: " if section else "") + piece,
                "metadata": {"feature": feature, "tier": tier, "doc": path.name, "section": section or path.stem,
                             "part": part, "label": f"{path.name} › {section or path.stem}", **extra},
            })
    return chunks


def row_chunk(feature, record, record_id, text, **meta):
    """One database row as a tier-1 chunk. Pass the columns worth filtering on as metadata."""
    clean = {k: v for k, v in meta.items() if v is not None}
    return {"id": f"{feature}:{record}/{record_id}", "text": text,
            "metadata": {"feature": feature, "tier": 1, "record": record, "record_id": record_id, **clean}}
