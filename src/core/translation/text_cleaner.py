import re


def is_translatable_text(text: str) -> bool:
    """
    Filters out noise, game telemetry, UI metrics, shortcuts, and pure numbers/symbols.
    Returns True ONLY if the text is a meaningful sentence or dialogue fragment.
    """
    if not text:
        return False
    s = text.strip()
    if len(s) < 3:
        return False

    # 1. Reject if pure numbers or numbers with signs (e.g. "100", "0", "-5", "3.14")
    if re.fullmatch(r"^[+-]?\d+([.,]\d+)?$", s):
        return False

    # 2. Reject pure symbols / punctuation (e.g. "...", "---", "/", "->", "=>")
    if re.fullmatch(r"^[\W_]+$", s):
        return False

    # 3. Reject game telemetry and UI metrics (e.g. "186ms", "60fps", "29m", "100km", "50%")
    if re.fullmatch(r"^\d+(\.\d+)?\s*(ms|fps|m|km|s|px|%|k|g)$", s, re.IGNORECASE):
        return False

    # 4. Reject single key prompts or bracketed keys (e.g. "<E>", "[F]", "(F)", "F", "E")
    if re.fullmatch(r"^[<\[(]?[A-Za-z0-9][>\])]?$", s):
        return False

    # 5. Reject level indicators (e.g. "L20", "Lv.50", "Lv20")
    if re.fullmatch(r"^(L|Lv|Level)\.?\s*\d+$", s, re.IGNORECASE):
        return False

    # 6. Reject user IDs and timestamps (e.g. "UserID:718261532", "UID: 12345", "08.12026-09-1806:59:44+7")
    if re.search(r"\b(uid|userid|user\s*id)[\s:]*\d+", s, re.IGNORECASE):
        return False
    if re.match(r"^\d{2,4}[-./]\d{2}[-./]\d{2,4}", s):
        return False

    # 7. Check alphabetic content ratio
    alpha_chars = [c for c in s if c.isalpha()]
    if len(alpha_chars) < 3:
        return False

    non_space_chars = [c for c in s if not c.isspace()]
    if len(alpha_chars) / len(non_space_chars) < 0.5:
        return False

    # 8. Must contain at least one real word with 2+ letters
    words = [w for w in re.findall(r"[A-Za-z]+", s) if len(w) >= 2]
    if not words:
        return False

    return True


def clean_ocr_text(text: str) -> str:
    """
    Normalizes and cleans raw OCR text from game dialogues.
    Fixes glued words, missing punctuation spacing, and artifacts that degrade
    machine translation quality.
    """
    if not text or not text.strip():
        return ""

    cleaned = text

    # 1. Space after punctuation if followed by a letter (e.g. "someday.I" -> "someday. I")
    cleaned = re.sub(r"([.,!?;:])([A-Za-z])", r"\1 \2", cleaned)

    # 2. Add space around isolated pronoun 'I' glued between words:
    # e.g. "whenIrealized" -> "when I realized", "thatIhad" -> "that I had"
    cleaned = re.sub(r"([a-z])(I)([a-z])", r"\1 \2 \3", cleaned)
    cleaned = re.sub(r"([a-z])(I\')", r"\1 \2", cleaned)
    cleaned = re.sub(r"([a-z])(I\b)", r"\1 \2", cleaned)

    # 3. Add space before capital letters if glued to lowercase (e.g. "ResonanceNexus" -> "Resonance Nexus")
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)

    # 4. Clean common OCR trailing junk and normalize quotes
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("’", "'")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip("_").rstrip(":")

    return cleaned
