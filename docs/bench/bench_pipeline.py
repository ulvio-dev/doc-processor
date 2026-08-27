"""Benchmark harness for issue #4. Writes results as JSON lines to stdout.

Each run is a fresh converter unless reuse=True, so the default numbers include
what the service actually pays today (a converter per request)."""
from __future__ import annotations
import json, os, sys, time, gc

os.environ.setdefault("OMP_NUM_THREADS", "4")

from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.accelerator_options import AcceleratorDevice
from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption
from io import BytesIO

CORPUS = sys.argv[1]
FILTER = sys.argv[2] if len(sys.argv) > 2 else ""

def load(name):
    with open(os.path.join(CORPUS, name), "rb") as f:
        return f.read()

def opts(do_ocr=True, table=True, mode=TableFormerMode.ACCURATE, threads=4, ocr_engine=None):
    o = PdfPipelineOptions()
    o.do_ocr = do_ocr
    o.do_table_structure = table
    o.table_structure_options.mode = mode
    o.accelerator_options.num_threads = threads
    o.accelerator_options.device = AcceleratorDevice.CPU
    if ocr_engine is not None:
        o.ocr_options = ocr_engine
    return o

def make_converter(fmt, o):
    return DocumentConverter(allowed_formats=[fmt], format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=o)})

def run(label, filename, o=None, fmt=InputFormat.PDF, reuse_conv=None, repeats=1):
    if FILTER and FILTER not in label:
        return
    data = load(filename)
    for r in range(repeats):
        gc.collect()
        t0 = time.perf_counter()
        conv = reuse_conv or make_converter(fmt, o)
        t1 = time.perf_counter()
        res = conv.convert(DocumentStream(name=filename, stream=BytesIO(data)))
        t2 = time.perf_counter()
        doc = res.document
        md = doc.export_to_markdown()
        t3 = time.perf_counter()
        rec = dict(label=label, file=filename, rep=r,
                   converter_init_s=round(t1-t0, 3), convert_s=round(t2-t1, 3),
                   export_s=round(t3-t2, 3), total_s=round(t3-t0, 3),
                   pages=len(getattr(doc, "pages", {}) or {}), md_chars=len(md))
        print(json.dumps(rec), flush=True)

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.backend.docling_parse_backend import DoclingParseDocumentBackend

TEXT, SCAN, DOCX, REAL = "nl_text.pdf", "nl_scan.pdf", "nl_procedure.docx", "arxiv_doclaynet.pdf"

def make_converter(fmt, o, backend=None):
    fo = PdfFormatOption(pipeline_options=o) if backend is None else PdfFormatOption(pipeline_options=o, backend=backend)
    return DocumentConverter(allowed_formats=[fmt], format_options={InputFormat.PDF: fo})

PDFIUM = PyPdfiumDocumentBackend

def run2(label, filename, o=None, fmt=InputFormat.PDF, backend=None, reuse=None, repeats=1):
    if FILTER and FILTER not in label: return
    data = load(filename)
    for r in range(repeats):
        gc.collect()
        t0=time.perf_counter()
        conv = reuse or make_converter(fmt, o, backend)
        t1=time.perf_counter()
        res=conv.convert(DocumentStream(name=filename, stream=BytesIO(data)))
        t2=time.perf_counter()
        doc=res.document; md=doc.export_to_markdown()
        t3=time.perf_counter()
        print(json.dumps(dict(label=label, file=filename, rep=r,
            converter_init_s=round(t1-t0,3), convert_s=round(t2-t1,3), export_s=round(t3-t2,3),
            total_s=round(t3-t0,3), pages=len(getattr(doc,"pages",{}) or {}), md_chars=len(md))), flush=True)

# --- 1. baseline, exactly as the service runs today (fresh converter per request)
run2("baseline", REAL, opts(), repeats=2)
run2("baseline", TEXT, opts(), backend=PDFIUM, repeats=2)
run2("baseline", DOCX, o=opts(), fmt=InputFormat.DOCX, repeats=2)

# --- 2. converter reuse (models loaded once)
_c = make_converter(InputFormat.PDF, opts())
run2("reuse-converter", REAL, reuse=_c, repeats=3)
del _c

# --- 3. levers, born-digital PDF
run2("no-ocr", REAL, opts(do_ocr=False), repeats=2)
run2("table-fast", REAL, opts(mode=TableFormerMode.FAST), repeats=2)
run2("no-ocr+table-fast", REAL, opts(do_ocr=False, mode=TableFormerMode.FAST), repeats=2)
run2("no-ocr+no-table", REAL, opts(do_ocr=False, table=False), repeats=2)
run2("no-ocr", TEXT, opts(do_ocr=False), backend=PDFIUM, repeats=2)
run2("no-ocr+table-fast", TEXT, opts(do_ocr=False, mode=TableFormerMode.FAST), backend=PDFIUM, repeats=2)
run2("no-ocr+no-table", TEXT, opts(do_ocr=False, table=False), backend=PDFIUM, repeats=2)

# --- 4. pdf backend comparison (same options)
run2("backend-pdfium", REAL, opts(do_ocr=False), backend=PDFIUM, repeats=2)
run2("backend-doclingparse", REAL, opts(do_ocr=False), backend=DoclingParseDocumentBackend, repeats=2)

# --- 5. threads
for n in (1,2,4,8):
    run2(f"threads-{n}", REAL, opts(do_ocr=False, mode=TableFormerMode.FAST, threads=n), repeats=2)

# --- 6. scanned pdf
run2("scan-defaults", SCAN, opts(), backend=PDFIUM, repeats=1)
run2("scan-no-ocr", SCAN, opts(do_ocr=False), backend=PDFIUM, repeats=1)
run2("scan-no-ocr+no-table", SCAN, opts(do_ocr=False, table=False), backend=PDFIUM, repeats=1)
