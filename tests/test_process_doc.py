"""The conversion library — real docling, no HTTP.

These are the only tests that actually run docling. They use .docx, which goes
through docling's SimplePipeline and needs no ML model downloads; a .pdf test
would pull ~500MB of layout models on a cold cache.
"""
from __future__ import annotations

import pytest

from src.process_doc import (
    ACCEPTED_FORMATS,
    DEFAULTS,
    MAX_QUEUE_ENTRIES,
    MAX_UPLOAD_BYTES,
    ProcessParams,
    UnsupportedFormat,
    detect_format,
    process_document,
)


def test_limits_match_the_contract():
    assert MAX_UPLOAD_BYTES == 20 * 1024 * 1024
    assert MAX_QUEUE_ENTRIES == 10


def test_accepted_formats_are_exactly_pdf_docx_doc():
    assert set(ACCEPTED_FORMATS) == {".pdf", ".docx", ".doc"}


@pytest.mark.parametrize(
    "name,expected",
    [
        ("a.pdf", "pdf"),
        ("A.PDF", "pdf"),
        ("report.docx", "docx"),
        ("legacy.doc", "doc"),
        ("dotted.name.v2.pdf", "pdf"),
    ],
)
def test_detect_format(name, expected):
    _, fmt = detect_format(name)
    assert fmt.value == expected


@pytest.mark.parametrize("name", ["notes.txt", "sheet.xlsx", "deck.pptx", "", "pdf"])
def test_detect_format_rejects_everything_else(name):
    with pytest.raises(UnsupportedFormat):
        detect_format(name)


def test_defaults_come_from_docling():
    """Not a tautology: it pins the *shape* the UI and README depend on.

    The values themselves are read off docling at import, so this fails loudly
    if an upgrade removes a key rather than letting the UI render undefined.
    """
    for key in ("do_ocr", "ocr_lang", "max_tokens", "tokenizer", "output"):
        assert key in DEFAULTS
    assert isinstance(DEFAULTS["max_tokens"], int) and DEFAULTS["max_tokens"] > 0
    assert DEFAULTS["output"] == "both"


def test_converts_docx_to_markdown_and_chunks(docx_bytes):
    result = process_document(docx_bytes, "report.docx")

    assert "# Quarterly Report" in result["markdown"]
    assert "12%" in result["markdown"]
    assert result["chunks"] and all(isinstance(c, str) for c in result["chunks"])
    assert result["meta"]["format"] == "docx"
    assert result["meta"]["size_bytes"] == len(docx_bytes)
    assert result["meta"]["chunk_count"] == len(result["chunks"])


def test_output_markdown_only_skips_chunking(docx_bytes):
    result = process_document(docx_bytes, "report.docx", ProcessParams(output="markdown"))
    assert result["markdown"]
    assert result["chunks"] is None
    assert result["meta"]["chunk_count"] is None


def test_output_chunks_only_skips_markdown(docx_bytes):
    result = process_document(docx_bytes, "report.docx", ProcessParams(output="chunks"))
    assert result["markdown"] is None
    assert result["chunks"]


def test_progress_callback_reports_stages_in_order(docx_bytes):
    seen: list[tuple[str, int]] = []
    process_document(docx_bytes, "report.docx", progress=lambda s, p: seen.append((s, p)))

    stages = [s for s, _ in seen]
    assert stages == ["converting", "exporting", "chunking", "done"]
    percentages = [p for _, p in seen]
    assert percentages == sorted(percentages)
    assert percentages[-1] == 100


def test_max_tokens_is_honoured(docx_bytes):
    """A smaller budget must not produce fewer chunks than a larger one."""
    small = process_document(
        docx_bytes, "report.docx", ProcessParams(output="chunks", max_tokens=32)
    )
    large = process_document(
        docx_bytes, "report.docx", ProcessParams(output="chunks", max_tokens=512)
    )
    assert len(small["chunks"]) >= len(large["chunks"])
    assert small["meta"]["params"]["max_tokens"] == 32


def test_meta_echoes_the_params_used(docx_bytes):
    params = ProcessParams(output="both", do_ocr=False, max_tokens=128)
    result = process_document(docx_bytes, "report.docx", params)
    echoed = result["meta"]["params"]
    assert echoed["do_ocr"] is False
    assert echoed["max_tokens"] == 128
    assert echoed["output"] == "both"


def test_unsupported_format_raises_before_any_work(docx_bytes):
    with pytest.raises(UnsupportedFormat):
        process_document(docx_bytes, "report.txt")


def test_doc_without_libreoffice_fails_with_an_explanation(docx_bytes, monkeypatch):
    """Legacy .doc needs `soffice`; the error must say so, not die inside docling."""
    monkeypatch.setattr("src.process_doc.libreoffice_available", lambda: False)
    with pytest.raises(RuntimeError, match="LibreOffice"):
        process_document(docx_bytes, "legacy.doc")
