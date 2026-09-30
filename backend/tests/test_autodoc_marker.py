from app.services.autodoc_marker import (
    AUTODOC_DOC_MARKER,
    ensure_autodoc_marker,
    has_autodoc_marker,
    is_substantial_documentation,
)


def test_has_marker():
    assert has_autodoc_marker(f"{AUTODOC_DOC_MARKER}\n# Doc")
    assert not has_autodoc_marker("# Doc sem marcador")
    assert not has_autodoc_marker(None)
    assert not has_autodoc_marker("")


def test_ensure_marker_adds_once():
    marked = ensure_autodoc_marker("# Título")
    assert marked.startswith(AUTODOC_DOC_MARKER)
    assert ensure_autodoc_marker(marked) == marked  # idempotente


def test_ensure_marker_empty_content():
    assert ensure_autodoc_marker("") == AUTODOC_DOC_MARKER


def test_substantial_documentation():
    assert not is_substantial_documentation(None)
    assert not is_substantial_documentation(AUTODOC_DOC_MARKER)  # só o marcador não conta
    assert not is_substantial_documentation("curto")
    assert is_substantial_documentation("x" * 300)
    # marcador não conta para o mínimo
    assert not is_substantial_documentation(AUTODOC_DOC_MARKER + "x" * 299 + "", min_chars=300)
    assert is_substantial_documentation(AUTODOC_DOC_MARKER + "\n\n" + "x" * 300)
