"""Second pass: fixed-overhead levers — batch polling interval, OCR render scale,
model-init cost per converter, and heading hierarchy."""
import gc, json, os, sys, time
from io import BytesIO
os.environ.setdefault("OMP_NUM_THREADS", "4")
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.accelerator_options import AcceleratorDevice
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

CORPUS = sys.argv[1]
def load(n): return open(os.path.join(CORPUS, n), "rb").read()

def opts(**kw):
    o = PdfPipelineOptions()
    o.accelerator_options.device = AcceleratorDevice.CPU
    o.accelerator_options.num_threads = kw.pop("threads", 4)
    o.do_ocr = kw.pop("do_ocr", True)
    o.do_table_structure = kw.pop("table", True)
    o.table_structure_options.mode = kw.pop("mode", TableFormerMode.ACCURATE)
    if "poll" in kw: o.batch_polling_interval_seconds = kw.pop("poll")
    if "ocr_scale" in kw: o.ocr_options.scale = kw.pop("ocr_scale")
    assert not kw, kw
    return o

def conv(o, backend=PyPdfiumDocumentBackend):
    return DocumentConverter(allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=o, backend=backend)})

def run(label, fn, o, repeats=1, reuse=None):
    data = load(fn)
    for r in range(repeats):
        gc.collect(); t0=time.perf_counter()
        c = reuse or conv(o)
        t1=time.perf_counter()
        res = c.convert(DocumentStream(name=fn, stream=BytesIO(data)))
        t2=time.perf_counter()
        print(json.dumps(dict(label=label, file=fn, rep=r, init_s=round(t1-t0,3),
            convert_s=round(t2-t1,3), pages=len(res.document.pages))), flush=True)

TEXT, SCAN, REAL = "nl_text.pdf", "nl_scan.pdf", "arxiv_doclaynet.pdf"

# fixed per-run overhead: poll interval on a cheap config
for p in (0.5, 0.1, 0.02):
    run(f"poll-{p}", TEXT, opts(do_ocr=False, table=False, poll=p), repeats=3)

# first vs later conversion on the SAME converter -> model load cost per request
o = opts(do_ocr=False, mode=TableFormerMode.FAST)
c = conv(o)
run("warm-1st", TEXT, None, reuse=c, repeats=1)
run("warm-2nd+", TEXT, None, reuse=c, repeats=3)
del c
run("cold-each", TEXT, opts(do_ocr=False, mode=TableFormerMode.FAST), repeats=3)

# OCR render scale on the scanned pdf
for s in (3.0, 2.0, 1.5):
    run(f"ocr-scale-{s}", SCAN, opts(ocr_scale=s, mode=TableFormerMode.FAST), repeats=1)
