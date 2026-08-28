"""How many tokens does the same Dutch text cost under different tokenizers,
and what does that do to HybridChunker's output?"""
import json, sys, time
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

CORPUS = sys.argv[1]
MODELS = [
    ("sentence-transformers/all-MiniLM-L6-v2", 256),
    ("intfloat/multilingual-e5-large", 512),
    ("intfloat/multilingual-e5-base", 512),
    ("BAAI/bge-m3", 8192),
    ("Alibaba-NLP/gte-multilingual-base", 8192),
    ("jinaai/jina-embeddings-v3", 8192),
    ("Qwen/Qwen3-Embedding-0.6B", 32768),
    ("NetherlandsForensicInstitute/robbert-2023-dutch-base-cross-encoder", 512),
]

conv = DocumentConverter(allowed_formats=[InputFormat.DOCX])
doc = conv.convert(f"{CORPUS}/nl_procedure.docx").document
text = doc.export_to_markdown()
words = len(text.split()); chars = len(text)
print(json.dumps({"kind": "corpus", "chars": chars, "words": words}), flush=True)

for name, ctx in MODELS:
    try:
        from transformers import AutoTokenizer
        t0 = time.perf_counter()
        tk = AutoTokenizer.from_pretrained(name)
        load = time.perf_counter() - t0
        t0 = time.perf_counter()
        n = len(tk.encode(text, add_special_tokens=False))
        enc = time.perf_counter() - t0
        rec = {"kind": "tok", "model": name, "vocab": len(tk), "ctx": ctx,
               "tokens": n, "tokens_per_word": round(n / words, 3),
               "chars_per_token": round(chars / n, 2),
               "load_s": round(load, 2), "encode_s": round(enc, 4)}
        # chunking behaviour at that model's own budget (capped at 512 for sanity)
        budget = min(ctx, 512)
        try:
            ht = HuggingFaceTokenizer.from_pretrained(name, max_tokens=budget)
            t0 = time.perf_counter()
            chunks = list(HybridChunker(tokenizer=ht).chunk(doc))
            rec["chunk_s"] = round(time.perf_counter() - t0, 2)
            sizes = [len(tk.encode(c.text, add_special_tokens=False)) for c in chunks]
            rec.update(budget=budget, chunks=len(chunks),
                       mean_tokens=round(sum(sizes)/len(sizes), 1), max_tokens_seen=max(sizes))
        except Exception as e:
            rec["chunk_error"] = f"{type(e).__name__}: {e}"[:200]
        print(json.dumps(rec), flush=True)
    except Exception as e:
        print(json.dumps({"kind": "tok", "model": name, "error": f"{type(e).__name__}: {e}"[:200]}), flush=True)
