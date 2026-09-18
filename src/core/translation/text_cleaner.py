import re

# Common English glued word patterns frequently observed in stylized game fonts
_COMMON_GLUED_PAIRS = [
    (r"\bcheckitout\b", "check it out"),
    (r"([a-z]+)(to\b)", r"\1 to"),
    (r"([a-z]+)(the\b)", r"\1 the"),
    (r"([a-z]+)(of\b)", r"\1 of"),
    (r"([a-z]+)(in\b)", r"\1 in"),
    (r"([a-z]+)(with\b)", r"\1 with"),
    (r"([a-z]+)(here\b)", r"\1 here"),
]


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
