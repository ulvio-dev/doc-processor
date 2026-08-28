# Doc Processor
#
# x86 only (linux/amd64) — the target is CPU nodes on OVH Cloud. There is no
# arm64 build any more; the old build.sh built both.
#
# Two things dominate this image and are worth knowing before editing it:
#   1. The docling + hybrid-chunk models are baked in, so a cold pod does not
#      download hundreds of MB on its first request.
#   2. LibreOffice is here solely so legacy .doc works — docling converts .doc
#      to .docx by shelling out to `soffice`. It is ~400MB. Drop the apt line
#      and .doc from ACCEPTED_FORMATS together if that trade is not worth it.

FROM python:3.13-bookworm

LABEL org.opencontainers.image.source=https://github.com/ulvio-dev/doc-processor
LABEL org.opencontainers.image.description="Convert PDF/DOCX/DOC to markdown + chunks over HTTP with SSE progress"

WORKDIR /app

# libgl1 + libglib2.0-0: opencv (cv2) needs libGL.so.1. Not optional — on Linux
# CPU, docling's default `auto` OCR resolves to RapidOCR, which imports cv2, so
# without these even `docling-tools models download` dies with
# "ImportError: libGL.so.1: cannot open shared object file".
#
# libreoffice-writer-nogui: legacy .doc only — docling converts .doc to .docx by
# shelling out to `soffice`. --no-install-recommends keeps the JVM and the rest
# of the office suite out.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libreoffice-writer-nogui \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Dependencies first, so a source-only change does not re-resolve or re-download
# torch. The project itself is not installable (flat main.py + src/), hence
# --no-install-project.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Model caches. Deliberately NOT /tmp (which the old image used): a pod that
# mounts an emptyDir over /tmp would wipe the baked models and the service would
# then try to reach huggingface.co on its first request.
ENV HF_HOME=/opt/hf
ENV TORCH_HOME=/opt/torch
ENV DOCLING_ARTIFACTS_PATH=/root/.cache/docling/models

RUN docling-tools models download

COPY main.py ./
COPY src/ ./src/

# Warm the chunking tokenizer into HF_HOME, rather than copying a
# hand-maintained cache tree into the image. The repo used to carry
# .hybrid-chunk-model/ for this. That cache holds only tokenizer files, and
# docling 2.123's HuggingFaceTokenizer also loads the model's config.json to
# derive max_tokens — so the copied tree was incomplete and the service died at
# import with "couldn't connect to huggingface.co" under HF_HUB_OFFLINE.
# Fetching exactly what is needed cannot drift out of date the same way.
#
# Which tokenizer is read off the service instead of named here:
# DEFAULT_TOKENIZER is not docling's default any more (see src/process_doc.py),
# and a second copy of that name is a copy that can drift. The cost of importing
# it from src/ is that this layer rebuilds on any source change; it fetches
# tokenizer files only, not model weights.
#
# Every tokenizer the API accepts is warmed, not just the default: /process
# rejects anything outside TOKENIZER_CHOICES precisely because HF_HUB_OFFLINE
# below means an uncached model cannot be fetched at runtime. The two lists are
# the same list, which is why this reads it rather than repeating it.
#
# Tokenizer files only — a few MB each. Qwen3-Embedding-8B's 16 GB of weights
# are never downloaded; nothing here embeds anything.
RUN python -c "\
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer; \
from src.process_doc import TOKENIZER_CHOICES, DEFAULT_MAX_TOKENS; \
[HuggingFaceTokenizer.from_pretrained(t, max_tokens=DEFAULT_MAX_TOKENS) for t in TOKENIZER_CHOICES]; \
print('tokenizers cached:', ', '.join(TOKENIZER_CHOICES))"

# Nothing should reach the network at runtime; the models above are all baked in.
# Set as a safety net so a missing model fails loudly at startup instead of
# silently downloading hundreds of MB on a pod's first request.
ENV HF_HUB_OFFLINE=1

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# On container runtimes always set a thread budget: without one, torch and OMP
# each size themselves to the host's core count, oversubscribe the pod's CPU
# quota and end up slower. Right value depends on the k8s CPU limit — see #4.
ENV OMP_NUM_THREADS=4

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# One worker, deliberately: the queue is in-process, so a second worker would
# mean a second independent queue and two conversions fighting for the same CPU.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
