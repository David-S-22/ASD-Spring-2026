from typing import List, Optional
from shared.backend import dto
from .ollama_service import classifier_model, load_prompt, prompt_model


def classify_feedback(feedback_text: str, categories: List[dto.Category]) -> tuple[Optional[int], Optional[str]]:
    """
    Classifies a single feedback sentence using the classifier model and classify_prompt.txt.
    Returns (category_id, timeframe) if an active focus request is identified,
    or (None, None) if it is general feedback or a constraint.
    """
    if not feedback_text or not feedback_text.strip() or not categories:
        return None, None

    category_names = [category.name for category in categories]
    prompt_template = load_prompt("classify_prompt.txt")
    prompt = prompt_template.format(
        valid_categories=", ".join(category_names),
        feedback_text=feedback_text.strip(),
    )

    try:
        data = prompt_model(prompt, model=classifier_model, json_mode=True)
        if data.get("is_focus"):
            matched_category = None
            if data.get("category"):
                matched_category = next(
                    (category for category in categories if category.name.lower() == str(data["category"]).lower()),
                    None,
                )
            timeframe = data.get("timeframe")
            if timeframe:
                timeframe = str(timeframe).strip()
                if timeframe.isdigit():
                    timeframe = f"{timeframe} weeks"
            if matched_category:
                return matched_category.id, timeframe
            if timeframe:
                return None, timeframe
    except Exception:
        pass

    return None, None
