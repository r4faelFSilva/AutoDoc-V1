"""Marcador e heurísticas para documentação gerada pelo AutoDoc."""

AUTODOC_DOC_MARKER = "<!-- autodoc:generated -->"

DEFAULT_MIN_DOC_CHARS = 300


def has_autodoc_marker(content: str | None) -> bool:
    if not content:
        return False
    return AUTODOC_DOC_MARKER in content


def ensure_autodoc_marker(content: str) -> str:
    text = content.strip()
    if not text:
        return AUTODOC_DOC_MARKER
    if has_autodoc_marker(text):
        return text
    return f"{AUTODOC_DOC_MARKER}\n\n{text}"


def is_substantial_documentation(content: str | None, min_chars: int = DEFAULT_MIN_DOC_CHARS) -> bool:
    if not content:
        return False
    stripped = content.strip()
    if not stripped:
        return False
    without_marker = stripped.replace(AUTODOC_DOC_MARKER, "").strip()
    return len(without_marker) >= min_chars
