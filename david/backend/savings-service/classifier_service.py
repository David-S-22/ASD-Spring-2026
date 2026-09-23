import logging
from typing import List, Optional
from shared.backend import dto
from .ollama_service import classifier_model, load_prompt, prompt_structured_schema

logger = logging.getLogger(__name__)


def classify_feedback(feedback_text: str, categories: List[dto.Category]) -> tuple[Optional[int], Optional[str]]:
    """
    Classifies a single feedback sentence using a grammar-constrained JSON schema.
    Returns (category_id, timeframe) if an active focus request is identified,
    or (None, None) if it is general feedback or a constraint.
    """
    if not feedback_text or not feedback_text.strip() or not categories:
        return None, None

    category_names = [category.name for category in categories]
    category_enum = category_names + ["null"]

    schema = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["focus", "constraint", "general"],
            },
            "category": {
                "type": "string",
                "enum": category_enum,
            },
            "timeframe": {
                "type": "string",
            },
        },
        "required": ["intent", "category", "timeframe"],
    }

    sys_prompt = load_prompt("classify_prompt.txt")

    try:
        data = prompt_structured_schema(
            prompt=feedback_text.strip(),
            schema=schema,
            model=classifier_model,
            system_prompt=sys_prompt,
        )
        if data.get("intent") == "focus":
            cat_val = data.get("category")
            matched_category = None
            if cat_val and str(cat_val).lower() != "null":
                cat_clean = str(cat_val).strip().lower()
                matched_category = next(
                    (category for category in categories if category.name.strip().lower() == cat_clean),
                    None,
                )
            timeframe_val = data.get("timeframe")
            timeframe = None
            if timeframe_val and str(timeframe_val).lower() not in ("null", "none", ""):
                timeframe = str(timeframe_val).strip()
                if timeframe.isdigit():
                    timeframe = f"{timeframe} weeks"
            if matched_category:
                return matched_category.id, timeframe
            if timeframe:
                return None, timeframe
    except Exception as e:
        logger.warning(f"Error classifying feedback '{feedback_text}': {e}")

    return None, None
