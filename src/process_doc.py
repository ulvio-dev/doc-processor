"""
Docling conversion, as a library.

Takes document *bytes* and returns markdown + chunks. Nothing is read from or
written to disk, and nothing is returned by reference — the caller (src/app.py)
streams the result straight back over SSE.

Every knob the HTTP API exposes has its default read off docling itself
(see DEFAULTS below) rather than restated here, so the UI shows what docling
would actually do and a docling upgrade cannot silently drift from the docs.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from io import BytesIO
from typing import Callable

from docling.chunking import HybridChunker
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

# Formats this service accepts. Docling 2.123 supports far more (xlsx, pptx,
# html, images, audio...), but the contract is deliberately narrow: enabling a
# format means owning its failure modes.
#
# .doc is the awkward one — docling handles it by shelling out to LibreOffice to
# produce a .docx first, so it only works when `soffice` is on PATH. See
# libreoffice_available().
ACCEPTED_FORMATS: dict[str, InputFormat] = {
    ".pdf": InputFormat.PDF,
    ".docx": InputFormat.DOCX,
    ".doc": InputFormat.DOC,
}

ACCEPTED_MEDIA_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}

# 20 MB per document, buffered in memory.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

MAX_QUEUE_ENTRIES = 10


# Set when the chunking tokenizer could not be loaded at import — almost always
# a model-cache problem in the image. Surfaced on /health so the frontend can say
# so, instead of the service dying at import and telling nobody.
TOKENIZER_ERROR: str | None = None

# Fallback used only if the tokenizer cannot be loaded. Docling derives this from
# the model config, so it is right for all-MiniLM-L6-v2 but may be stale for
# another model; TOKENIZER_ERROR is what tells you the value is a guess.
_FALLBACK_MAX_TOKENS = 256


def _docling_defaults() -> dict:
    """Docling's own defaults for the parameters we expose.

    Read off docling rather than hardcoded, so the README and the UI stay honest
    across upgrades.

    Instantiating HybridChunker touches the tokenizer, which means the HF cache.
    A broken cache must not stop the service from starting: the frontend is
    supposed to be where you find out what is wrong, and it cannot be if the
    process exits at import.
    """
    global TOKENIZER_ERROR

    pdf = PdfPipelineOptions()

    try:
        max_tokens = HybridChunker().tokenizer.max_tokens
    except Exception as e:
        TOKENIZER_ERROR = f"{type(e).__name__}: {e}"
        max_tokens = _FALLBACK_MAX_TOKENS

    return {
        "do_ocr": pdf.do_ocr,
        "ocr_lang": list(pdf.ocr_options.lang),
        "max_tokens": max_tokens,
        "tokenizer": DEFAULT_TOKENIZER,
        "output": "both",
        # Not exposed as request parameters, but worth reporting so the UI can
        # show what the conversion is actually doing.
        "do_table_structure": pdf.do_table_structure,
        "table_mode": pdf.table_structure_options.mode.value,
        "num_threads": pdf.accelerator_options.num_threads,
    }


# The chunking model baked into the image (.hybrid-chunk-model/), and docling's
# own HybridChunker default.
DEFAULT_TOKENIZER = "sentence-transformers/all-MiniLM-L6-v2"

DEFAULTS = _docling_defaults()

OUTPUT_CHOICES = ("markdown", "chunks", "both")


def libreoffice_available() -> bool:
    """Whether legacy .doc can actually be converted in this environment."""
    return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


@dataclass
class ProcessParams:
    """Validated request parameters. `None` means "use docling's default"."""

    output: str = "both"
    do_ocr: bool = DEFAULTS["do_ocr"]
    ocr_lang: list[str] = field(default_factory=list)
    max_tokens: int | None = None
    tokenizer: str = DEFAULT_TOKENIZER

    @property
    def wants_markdown(self) -> bool:
        return self.output in ("markdown", "both")

    @property
    def wants_chunks(self) -> bool:
        return self.output in ("chunks", "both")


class UnsupportedFormat(ValueError):
    """Raised for a file extension outside ACCEPTED_FORMATS."""


def detect_format(filename: str) -> tuple[str, InputFormat]:
    """Map a filename to its docling InputFormat, or raise UnsupportedFormat."""
    lowered = (filename or "").lower()
    for ext, fmt in ACCEPTED_FORMATS.items():
        if lowered.endswith(ext):
            return ext, fmt
    raise UnsupportedFormat(
        f"unsupported file type: {filename!r}. "
        f"Accepted: {', '.join(sorted(ACCEPTED_FORMATS))}"
    )


def _build_converter(params: ProcessParams, fmt: InputFormat) -> DocumentConverter:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = params.do_ocr
    if params.ocr_lang:
        pipeline_options.ocr_options.lang = list(params.ocr_lang)

    # allowed_formats is restricted to the one format in play so an extension
    # that lies about its content fails loudly instead of being sniffed into
    # some other pipeline.
    return DocumentConverter(
        allowed_formats=[fmt],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)},
    )


def _build_chunker(params: ProcessParams) -> HybridChunker:
    if params.max_tokens is None and params.tokenizer == DEFAULT_TOKENIZER:
        return HybridChunker()
    tokenizer = HuggingFaceTokenizer.from_pretrained(
        params.tokenizer, max_tokens=params.max_tokens
    )
    return HybridChunker(tokenizer=tokenizer)


# Called between stages so the caller can emit SSE progress. Blocking function,
# invoked from the worker thread — see app._run_in_thread.
Progress = Callable[[str, int], None]


def process_document(
    data: bytes,
    filename: str,
    params: ProcessParams | None = None,
    progress: Progress | None = None,
) -> dict:
    """Convert `data` to markdown and/or chunks.

    Returns {"markdown": str | None, "chunks": list[str] | None, "meta": {...}}.
    Blocking and CPU-bound: run it in a thread, never on the event loop.
    """
    params = params or ProcessParams()
    _, fmt = detect_format(filename)

    if fmt is InputFormat.DOC and not libreoffice_available():
        raise RuntimeError(
            "legacy .doc needs LibreOffice (`soffice`) on PATH — docling converts "
            "it to .docx first. Either install LibreOffice or convert to .docx."
        )

    def report(stage: str, pct: int) -> None:
        if progress:
            progress(stage, pct)

    report("converting", 5)
    converter = _build_converter(params, fmt)
    result = converter.convert(DocumentStream(name=filename, stream=BytesIO(data)))
    document = result.document

    markdown = None
    if params.wants_markdown:
        report("exporting", 70)
        markdown = document.export_to_markdown()

    chunks = None
    if params.wants_chunks:
        report("chunking", 80)
        chunker = _build_chunker(params)
        chunks = [chunk.text for chunk in chunker.chunk(document)]

    report("done", 100)

    return {
        "markdown": markdown,
        "chunks": chunks,
        "meta": {
            "filename": filename,
            "format": fmt.value,
            "size_bytes": len(data),
            "pages": len(getattr(document, "pages", {}) or {}) or None,
            "chunk_count": len(chunks) if chunks is not None else None,
            "params": {
                "output": params.output,
                "do_ocr": params.do_ocr,
                "ocr_lang": params.ocr_lang,
                "max_tokens": params.max_tokens or DEFAULTS["max_tokens"],
                "tokenizer": params.tokenizer,
            },
        },
    }
