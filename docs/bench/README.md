# Benchmark scripts for #4

The numbers in [../docling-performance.md](../docling-performance.md) came from
these. They are throwaway measurement tools, not part of the service — nothing
in `src/` imports them.

```bash
uv run --with reportlab python docs/bench/make_corpus.py /tmp/corpus
curl -sL -o /tmp/corpus/arxiv_doclaynet.pdf https://arxiv.org/pdf/2206.01062v1

uv run python docs/bench/bench_pipeline.py   /tmp/corpus   # OCR, tables, threads, backends
uv run python docs/bench/bench_overheads.py  /tmp/corpus   # converter reuse, polling, OCR scale
uv run python docs/bench/bench_tokenizers.py /tmp/corpus   # token counts and chunk sizes
```

Each writes one JSON object per run to stdout; logs go to stderr, so redirect
stdout to a `.jsonl` and summarise from there. `bench_pipeline.py` takes an
optional second argument that filters runs by label substring.

Re-run these after a docling upgrade — 2.122 and 2.123 both changed things that
move them.
