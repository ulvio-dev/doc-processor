# Docling: version, speed, and chunking for the RAG corpus

Investigation for [#4](https://github.com/ulvio-dev/doc-processor/issues/4).

**Status: recommendation 1 (the tokenizer and chunk budget) has since been
applied** — `DEFAULT_TOKENIZER = "intfloat/multilingual-e5-large"`,
`DEFAULT_MAX_TOKENS = 450`. `tokenizer` is now a closed list
(`TOKENIZER_CHOICES`: e5-large, `Qwen/Qwen3-Embedding-8B`, all-MiniLM-L6-v2),
all three warmed into the image at build time and validated on `/process`,
since the container cannot fetch an uncached model at runtime. Qwen is offered
because the RAG side may embed with Qwen3-8B; note that 450 e5 tokens is about
550 Qwen tokens of the same text. Everything
else here is still a proposal: no converter option, dependency pin or thread
setting was changed. The benchmark scripts that produced the numbers are under
[docs/bench/](bench/).

Context that shaped the recommendations: the consumer is a RAG application over
~600 documents — processes and procedures of a Belgian psychiatric centre,
mostly PDF and DOCX, in Dutch.

---

## Summary

1. **The single biggest speed lever is OCR, and it is pure waste on this
   corpus.** On a born-digital PDF, `do_ocr=False` produces *byte-identical*
   markdown in **a third of the time** (31.6 s → 8.7 s on a 9-page PDF; 14.5 s →
   5.5 s on a 12-page one). It cannot simply be switched off, because a scanned
   PDF then yields **zero characters, silently**. The change worth making is
   "OCR only when the page has no text layer", not "OCR off".
2. **The chunking tokenizer is wrong for Dutch, and that costs retrieval
   quality, not milliseconds.** `all-MiniLM-L6-v2` is an English model whose
   tokenizer splits Dutch into **1.5× more tokens** than the XLM-R tokenizer
   every serious multilingual embedding model uses. On a long-section Dutch
   procedure, today's `max_tokens=350` yields chunks averaging **178 tokens as
   the embedding model counts them — 35 % of a 512-token window**, and twice as
   many chunks as needed. This is the recommendation I would act on first.
3. **Docling is already current.** `uv.lock` resolves to **2.123.0**, which is
   the latest release on PyPI. Nothing has been published to GHCR yet, so there
   is no older production image to compare against — the version question is
   closed by the rewrite, not open.
4. **Do not buy more CPU per pod.** Conversion scales badly past 2 threads
   (1 → 4 threads buys 19 %, 8 threads is slower than 4). Two CPUs per pod and
   more pods, which is what the architecture already assumes.
5. One robustness finding that is not about speed: the default `docling-parse`
   backend **segfaulted** on one of the test PDFs, taking the whole process
   down. In a single-worker service that kills every queued job. See
   [Robustness](#robustness-a-crashing-backend-takes-the-queue-with-it).

---

## Baseline

### Versions

| Package | Version |
|---|---|
| docling | **2.123.0** (latest on PyPI as of 2026-08-27) |
| docling-core | 2.92.0 |
| docling-ibm-models | 3.14.0 |
| docling-parse | 7.16.0 |
| torch | 2.13.0 |
| transformers | 5.8.1 |

The issue asked which version the *running image* resolved to. There is no
running image: `GET /orgs/ulvio-dev/packages/container/doc-processor/versions`
returns 404 and the repo has no workflow runs. The first GHCR build will carry
whatever `uv.lock` says, which today is 2.123.0.

Defaults in force in `PdfPipelineOptions()`: `do_ocr=True`,
`do_table_structure=True`, `table_mode=ACCURATE`, `ocr_options=auto` (resolves
to RapidOCR/PP-OCRv6 on Linux CPU), `ocr_options.scale=3.0`, `num_threads=4`,
`device=auto`.

### Method, and how far to trust it

Measurements were taken on the development machine — **macOS on Apple Silicon,
10 cores, `device=CPU` forced, `OMP_NUM_THREADS=4`** — not on an OVH x86 node.
Absolute wall-clock numbers therefore do not transfer; **ratios between
configurations do**, and every recommendation below rests on a ratio. Two things
in particular need re-checking on the target hardware: the OCR engine (`auto`
resolves to RapidOCR on Linux, which is what production will use) and the
segfault.

[docs/bench/](bench/) reproduces everything:

```bash
uv run --with reportlab python docs/bench/make_corpus.py /tmp/corpus
uv run python docs/bench/bench_pipeline.py   /tmp/corpus   # levers
uv run python docs/bench/bench_overheads.py  /tmp/corpus   # fixed overheads
uv run python docs/bench/bench_tokenizers.py /tmp/corpus   # chunking
```

The corpus is synthetic and deliberately shaped like the real one — a Dutch
intake procedure with numbered steps, a responsibilities table and references:

| File | What it is |
|---|---|
| `nl_procedure.docx` | 12 sections, 7 tables, 2 144 words |
| `nl_text.pdf` | the same content as a 12-page born-digital PDF |
| `nl_scan.pdf` | `nl_text.pdf` rasterised to 200 dpi greyscale — no text layer |
| `arxiv_doclaynet.pdf` | a real 9-page paper, as a control for complex layout |

### What this did not measure

Three items from the issue's plan are deliberately not answered here, because
this machine cannot answer them honestly:

- **OCR engine comparison (EasyOCR vs Tesseract vs RapidOCR) on x86.** Docling's
  `auto` resolves per platform; the numbers above are whatever `auto` picked
  here. Since recommendation 2 removes OCR from the majority path entirely, this
  only matters for the scanned minority — measure it on an OVH node, and only if
  that minority turns out to be large.
- **Cold-start on the real image.** Models are baked in and load once per
  process, which is confirmed; how long a pod takes to serve its first request
  on OVH hardware is not.
- **Whether the segfault reproduces on linux/amd64.** The local Docker VM has
  1.9 GiB of memory, which is not enough to run this image at all.

**The one thing to redo before signing off** is to run this against ~20 real
documents from the centre. Everything here is a ratio measured on documents I
made up to look like theirs.

---

## Measurements

### Per-document conversion (seconds, mean of 2–3 runs)

| Configuration | `nl_text.pdf` (12 p) | `arxiv` (9 p) | `nl_scan.pdf` (12 p) | `nl_procedure.docx` |
|---|---|---|---|---|
| **as the service runs today** | **14.5** | **31.6** | **36.1** | **0.26** |
| `do_ocr=False` | 5.5 | 8.7 | 6.9 ⚠️ | — |
| `do_ocr=False` + table `FAST` | 4.2 | 5.3 | — | — |
| `do_ocr=False` + no tables | 2.8 | 2.6 | 3.1 ⚠️ | — |
| table `FAST` only (OCR on) | — | 30.1 | — | — |

⚠️ = **zero characters of output.** A scanned PDF without OCR converts fast and
returns nothing at all; the caller gets an empty markdown string and no error.

### Does OCR change the output on a born-digital PDF?

No. Markdown length is identical to the byte:

| Document | OCR on | OCR off |
|---|---|---|
| `nl_text.pdf` | 16 578 chars | 16 578 chars |
| `arxiv_doclaynet.pdf` | 51 187 chars | 51 187 chars |

Three times the wall clock for an identical document.

### TableFormer `ACCURATE` vs `FAST`

39 % faster on the non-OCR path (8.7 s → 5.3 s). Quality on the Dutch
responsibility tables: **6 of 7 tables extract identically**. The one difference
is a table continued across a page break, where `ACCURATE` recognises the
repeated header row and `FAST` treats it as data:

```
ACCURATE   0,1,2,3                                   <- header recognised
           Medicatieanamnese,Apotheker,48 uur,...
FAST       Medicatieanamnese,Apotheker,48 uur,...    <- header row lost
```

For retrieval that difference is close to irrelevant — the cell text is present
either way. For a procedure whose table *is* the content, it is a real, if
small, loss.

### Threads (`arxiv`, `do_ocr=False`, table `FAST`)

| `num_threads` | seconds | vs 1 thread |
|---|---|---|
| 1 | 6.38 | — |
| 2 | 5.59 | 1.14× |
| 4 | 5.20 | 1.23× |
| 8 | 5.66 | 1.13× (slower than 4) |

Docling's own threading is stage-parallel (OCR / layout / table run as separate
threads over a bounded queue), so a single document cannot use many cores well.
**Four threads is already past the knee, and eight is a regression.**

### PDF backend

| Backend | `arxiv`, `do_ocr=False` | markdown |
|---|---|---|
| `pypdfium2` | 8.51 s | 51 304 chars |
| `docling-parse` (default) | 9.02 s | 51 608 chars |

6 % apart. Not a speed lever.

### Fixed overheads

| What | Measured | Verdict |
|---|---|---|
| Building a `DocumentConverter` per request | 5.35 s cold vs 3.43 s warm on the same converter (`nl_text.pdf`, no OCR) → **~1.9 s per request** | Real, worth reclaiming for short documents. Invisible when OCR dominates (31.6 s vs 31.1 s on `arxiv`). |
| `batch_polling_interval_seconds` 0.5 → 0.02 | within noise (3.5 s vs 3.2 s) | Not a lever. |
| `ocr_options.scale` 3.0 → 1.5 | 39.1 s → 34.6 s on the scan (12 %) | Minor, and it trades OCR accuracy. Leave it. |
| Chunking (all tokenizers) | 0.03–0.07 s per document | **Chunking is free.** The tokenizer question below is about quality, not speed. |
| Model load at import | happens once per process, models baked into the image | Confirmed fine. |

---

## Chunking and the tokenizer

This is the section that matters most for the RAG application, and it is not a
performance question at all.

### What the tokenizer is actually for

`HybridChunker` uses a tokenizer only to *count*: it merges neighbouring
document elements while they fit inside `max_tokens`, and splits them when they
do not. The count is only meaningful if it is the same count the **embedding
model** will make. Docling's own documentation puts it plainly — the tokenizer
is "typically to be aligned to the embedding model tokenizer".

Today the service counts with `sentence-transformers/all-MiniLM-L6-v2`: an
English-only model, a 30 k WordPiece vocabulary, a 256-token window.

### Dutch costs 50 % more tokens under MiniLM

Same Dutch procedure text (2 144 words, 16 565 characters), different tokenizers:

| Tokenizer | Vocab | Tokens | Tokens / word | Chars / token |
|---|---|---|---|---|
| `all-MiniLM-L6-v2` (today) | 30 522 | **6 014** | **2.81** | 2.75 |
| `multilingual-e5-large` / `-base` | 250 002 | 4 018 | 1.87 | 4.12 |
| `BAAI/bge-m3` | 250 002 | 4 018 | 1.87 | 4.12 |
| `Alibaba-NLP/gte-multilingual-base` | 250 002 | 4 018 | 1.87 | 4.12 |
| `jinaai/jina-embeddings-v3` | 250 002 | 4 018 | 1.87 | 4.12 |
| `clips/e5-{small,base,large}-trm-nl` | 50 002 | 4 018 | 1.87 | 4.12 |
| `Qwen/Qwen3-Embedding-0.6B` | 151 669 | 4 945 | 2.31 | 3.35 |
| `robbert-2023-dutch` (Dutch BPE) | 50 000 | 4 967 | 2.32 | 3.34 |

**Every XLM-R-derived tokenizer gives exactly the same count** — including the
Dutch-trimmed CLiPS models, whose 50 k vocabulary is the XLM-R vocabulary with
the other languages removed. That is a convenient fact: it means the chunking
decision does not force the embedding-model decision.

### What that does to the chunks

Chunk sizes below are measured **in `multilingual-e5` tokens** — what the
embedding model would see — for a Dutch procedure with long, unbroken sections:

| Chunking configuration | Chunks | Mean size | Max | Window used (of 512) |
|---|---|---|---|---|
| MiniLM @ 256 (docling's default) | 96 | 89 | 89 | 17 % |
| **MiniLM @ 350 (today's service)** | **48** | **178** | **178** | **35 %** |
| e5 @ 512 | 24 | 356 | 445 | 70 % |
| bge-m3 @ 1024 | 16 | 534 | 979 | 104 % ⚠️ |

Today's setting produces **twice the chunks at half the intended size**. For 600
procedure documents that means a larger index, procedures fragmented across more
chunks, and less of each procedure visible per retrieved chunk at a fixed
top-*k*.

Two caveats worth keeping in view:

- **The budget only binds on long sections.** On a document with many short
  headed subsections, chunk size is decided by structure, not by `max_tokens` —
  MiniLM @ 350 and e5 @ 512 produce identical output there (55 chunks, mean 69
  tokens). The tokenizer choice matters exactly where sections are long, which
  is where over-splitting hurts.
- **Bigger is not better.** bge-m3 allows 8 192 tokens; chunking at 1 024
  produced a 979-token chunk, and dense retrieval degrades well before a model's
  window is full. 350–500 tokens is the range to aim at, not the model maximum.

### Which embedding model — and therefore which tokenizer

The relevant public evidence for Dutch is **MTEB-NL** ([arXiv
2509.12340](https://arxiv.org/abs/2509.12340), CLiPS / University of Antwerp),
40 Dutch datasets. Retrieval column (`Rtr`) from its Table 2:

| Model | Params | Dutch retrieval | Notes |
|---|---|---|---|
| Qwen3-Embedding-4B | 4 B | **64.2** | too heavy for a CPU node |
| multilingual-e5-large-instruct | 560 M | **61.4** | best of the practical options; needs query instructions |
| bge-m3 | 568 M | 60.0 | 8 192 ctx, dense+sparse+multi-vector |
| multilingual-e5-large | 560 M | 59.1 | plain `query:` / `passage:` prefixes |
| jina-embeddings-v3 | 572 M | 59.1 | |
| **clips/e5-large-trm-nl** | 355 M | 58.2 | best non-instruct model in the paper |
| Qwen3-Embedding-0.6B | 596 M | 57.1 | |
| gte-multilingual-base | 305 M | 56.8 | |
| **clips/e5-base-trm-nl** | 124 M | 56.5 | matches jina-v3 at ⅕ the size |
| multilingual-e5-base | 278 M | 55.8 | |
| clips/e5-small-trm-nl | 41 M | 53.1 | |

**Recommendation, in order:**

1. **`intfloat/multilingual-e5-large-instruct`** (or plain `multilingual-e5-large`)
   if the corpus is not purely Dutch — a Belgian psychiatric centre will
   plausibly hold French documents, KB/AR legislation and English clinical
   references, and a Dutch-only model embeds those badly. 512-token window,
   MIT-compatible licence, runs on CPU: 600 documents is a one-off batch of a
   few thousand chunks, minutes of work.
2. **`clips/e5-base-trm-nl`** if the corpus really is Dutch-only and you want
   the smallest thing that performs — 124 M parameters, MIT, trained by a
   Flemish group on Dutch data, and it beats models four times its size on
   Dutch retrieval.
3. Not Qwen3-0.6B: worse on Dutch than either, heavier, and a different
   tokenizer (2.31 tokens/word) that would have to be tracked here too.

**For this service, all three of options 1 and 2 imply the same change:** count
chunks with the XLM-R tokenizer. Concretely — `DEFAULT_TOKENIZER =
"intfloat/multilingual-e5-large"` and `DEFAULT_MAX_TOKENS = 450` (leaving room
under 512 for the `query:`/`passage:` prefix and special tokens). If the RAG side
later moves from `multilingual-e5-large` to `e5-base-trm-nl` or `bge-m3`, the
chunk counts do not change at all.

Three operational consequences, all of them easy to miss:

- The image runs with `HF_HUB_OFFLINE=1`, so **the new tokenizer must be warmed
  into `/opt/hf` at build time**, exactly as `HybridChunker()` is today.
  Otherwise the service dies at import — or rather, sets `TOKENIZER_ERROR` and
  tells you so in the UI, which is the reason that mechanism exists.
- `all-MiniLM-L6-v2` should stay downloadable in the image while any consumer
  still passes `tokenizer=` explicitly.
- E5 models expect `passage: ` on documents and `query: ` on queries at
  *embedding* time. That is the RAG application's job, not this service's, but
  getting it wrong silently costs more retrieval quality than any chunking
  parameter here.

### Stale documentation, spotted in passing

`README.md` listed `max_tokens` default `256` while the code set `350`. Fixed
along with the change above; `GET /api/contract` was right throughout, per the
design.

---

## Recommendations, ranked

### Apply now (safe, measured, reversible)

| # | Change | Effect | Risk |
|---|---|---|---|
| 1 ✅ | **Applied.** `DEFAULT_TOKENIZER` → `intfloat/multilingual-e5-large`, `DEFAULT_MAX_TOKENS` → 450, tokenizer warmed in the Dockerfile | halves the chunk count; chunks sized as the embedding model actually counts them | Re-embedding the corpus. Do it before the 600 documents are ingested, not after. |
| 2 | Skip OCR when the page already has a text layer; keep `do_ocr` as an explicit per-request override | **2.6–3.6× faster** on the born-digital majority, output unchanged | Needs the detection to be right — see below |
| 3 | Reuse `DocumentConverter` instances across requests (cache keyed by the options that build them) | ~1.9 s per request on short documents | Low. Concurrency is 1, so no sharing hazard. |

On (2), "OCR off by default" alone is **not** safe: it turns a scanned document
into an empty result with no error. The shape that works is per-page — convert
with OCR disabled, and if the extracted text is empty or implausibly short for
the page count, convert again with OCR on and say so in the `meta`. Cost is one
wasted fast pass on genuinely scanned documents (6.9 s of the 36 s), and the
service stops lying about scanned input.

### Worth trying, needs their documents

| Change | Effect | Why it is not in the list above |
|---|---|---|
| TableFormer `FAST` as the default | −39 % on the non-OCR path | Loses a repeated header row on page-break-split tables. Decide on real tables. |
| `ocr_options.scale` 3.0 → 2.0 | −12 % on scanned documents only | Trades OCR accuracy on what is already the minority case. |

### Not worth it

- **Switching PDF backend** — 6 %, within the noise of document variation.
- **More CPU per pod** — 4 threads is past the knee, 8 is slower.
- **More uvicorn workers** — each gets its own queue, so the cap stops meaning
  anything. Already documented in `CLAUDE.md`; the thread numbers say it also
  would not help.
- **`batch_polling_interval_seconds`** — no measurable effect.
- **Upgrading docling** — already on the latest release.

### Version pin

Keep the constraint unpinned in `pyproject.toml` with `uv.lock` recording
2.123.0, as `CLAUDE.md` prescribes. Add one rule: **re-run `docs/bench/` on a
docling bump.** 2.122 changed layout/table cell matching and 2.123 changed the
docling-parse default; both are exactly the sort of change that moves these
numbers underneath us.

---

## Kubernetes sizing

These are the resources the recommendations assume, not a measured tuning:

```yaml
resources:
  requests: { cpu: "2", memory: "4Gi" }
  limits:   { cpu: "2", memory: "4Gi" }   # requests == limits: Guaranteed QoS
env:
  - { name: OMP_NUM_THREADS, value: "2" } # match the CPU limit exactly
```

Reasoning: conversion gains 14 % from the second thread and 8 % more from the
third and fourth combined, so two CPUs is where the money stops working.
`OMP_NUM_THREADS` **must** equal the CPU limit — torch and OMP otherwise size
themselves to the *node's* core count, oversubscribe the cgroup quota and get
throttled into being slower. The Dockerfile currently hardcodes `4`; if the pod
is given 2 CPUs, that is already a misconfiguration.

Memory: peak is dominated by the layout and TableFormer models plus a 20 MB
document held in memory; 4 GiB is comfortable and 2 GiB is the floor I would not
go under. Throughput scales with pods, and the in-process queue caps each pod at
10 waiting jobs.

Ingesting the whole corpus is not a capacity problem either way. 600 documents,
assuming the measured per-document times and a 50/50 PDF/DOCX split: roughly
**75 minutes today**, roughly **30 minutes** with OCR skipped on born-digital
input — a single pod, once.

---

## Which levers belong in the API

Per-request (a caller can reasonably need something else):

| Parameter | Status |
|---|---|
| `do_ocr` | already exposed — keep, and make it a genuine three-way: `auto` (detect) / `true` / `false` |
| `ocr_lang` | already exposed — `nl,fr` is the sensible default for this corpus |
| `max_tokens`, `tokenizer` | already exposed — a caller embedding with a different model must be able to say so |
| `table_mode` | **propose adding**: `accurate` / `fast` / `off`, since it is 39 % of the non-OCR path and the right answer depends on the document |

Fixed (deployment-level, not a caller's business): `num_threads`, `device`,
`ocr_options.scale`, backend choice, batching and queue parameters.

---

## Robustness: a crashing backend takes the queue with it

While benchmarking, the default `docling-parse` backend **segfaulted** on the
generated `nl_text.pdf` — a SIGSEGV inside native code, not a Python exception:

```
Fatal Python error: Segmentation fault
  File ".../docling_parse/pdf_parser.py", line 1608 in get_task
  File ".../docling/backend/docling_parse_backend.py", line 656 in iter_pages
```

The same file converts fine through the `pypdfium2` backend, and the real
`arxiv` PDF converts fine through both — so this is one malformed-but-valid PDF
hitting a bug in `docling-parse` 7.16, not a general failure.

It still matters here. The service is one process with one worker and an
in-process queue: a segfault takes down the conversion **and every job waiting
behind it**, and the client sees a dropped SSE stream rather than an error in
the service's own words.

Not fixed, not investigated further — it is outside this issue. Recorded because
it should become its own issue, with two things to settle: does it reproduce on
linux/amd64, and is the answer "run conversion in a subprocess" (the queue
survives; the job fails cleanly) or "catch it at the pod level and let
Kubernetes restart" (simpler, loses the queue).

---

## Open questions for sign-off

1. **What embeds the chunks?** Everything in the chunking section follows from
   that one answer. If it is not decided yet, `multilingual-e5-large` is the
   choice that keeps the most doors open.
2. **Is the corpus Dutch-only, or Dutch + French + English?** Dutch-only makes
   `clips/e5-base-trm-nl` the better model; anything mixed rules it out.
3. **How many of the 600 documents are scans?** If the answer is "almost none",
   recommendation 2 is the whole speed story. If it is "a third", the OCR engine
   on x86 deserves its own measurement.
4. **May I re-run `docs/bench/` against ~20 real documents** before any of this
   is implemented? Synthetic Dutch procedures got the ratios; their documents
   would confirm them.
