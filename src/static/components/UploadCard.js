// The upload form and the live run. Parameter defaults come from
// /api/contract, so the form always offers what the service actually does.
function UploadCard({ contract, onEvent, onFinish, running, setRunning }) {
  const { useState, useRef, useEffect } = React;
  const [file, setFile] = useState(null);
  const [output, setOutput] = useState('both');
  const [doOcr, setDoOcr] = useState(true);
  const [ocrLang, setOcrLang] = useState('');
  const [maxTokens, setMaxTokens] = useState('');
  const [tokenizer, setTokenizer] = useState('');
  const [localError, setLocalError] = useState(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  // Seed the form from the service's real defaults once they arrive.
  useEffect(() => {
    if (!contract) return;
    setOutput(contract.defaults.output);
    setDoOcr(contract.defaults.do_ocr);
  }, [contract]);

  const maxBytes = contract ? contract.max_upload_bytes : 20 * 1024 * 1024;
  const accepted = contract ? contract.accepted_extensions : ['.pdf', '.docx', '.doc'];
  const defaults = contract ? contract.defaults : {};

  function pick(f) {
    setLocalError(null);
    if (!f) return setFile(null);
    const ext = '.' + (f.name.split('.').pop() || '').toLowerCase();
    if (!accepted.includes(ext)) {
      setLocalError(`${f.name} is not an accepted type. Accepted: ${accepted.join(', ')}.`);
      return setFile(null);
    }
    if (f.size > maxBytes) {
      setLocalError(
        `${f.name} is ${fmtBytes(f.size)} — the limit is ${fmtBytes(maxBytes)} per document.`
      );
      return setFile(null);
    }
    if (ext === '.doc' && contract && contract.libreoffice === false) {
      setLocalError(
        'This service has no LibreOffice installed, so legacy .doc cannot be converted. Save it as .docx first.'
      );
      return setFile(null);
    }
    setFile(f);
  }

  async function submit() {
    if (!file) return;
    setLocalError(null);
    setRunning(true);

    const body = new FormData();
    body.append('file', file);
    body.append('output', output);
    body.append('do_ocr', String(doOcr));
    if (ocrLang.trim()) body.append('ocr_lang', ocrLang.trim());
    if (String(maxTokens).trim()) body.append('max_tokens', String(maxTokens).trim());
    if (tokenizer.trim()) body.append('tokenizer', tokenizer.trim());

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch('/process', { method: 'POST', body, signal: controller.signal });

      if (!res.ok) {
        // Rejections arrive as plain HTTP, before any stream. Show the
        // service's own words rather than inventing a friendlier version.
        let detail = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          detail = j.error ? `${j.error} — ${j.detail || ''}` : j.detail || detail;
        } catch (e) { /* non-JSON body; keep the status */ }
        onEvent({ status: 'error', message: `${res.status}: ${detail}` });
        return;
      }

      await readSSE(res, onEvent, () => onEvent({ heartbeat: true }));
    } catch (e) {
      if (e.name !== 'AbortError') onEvent({ status: 'error', message: e.message });
    } finally {
      setRunning(false);
      abortRef.current = null;
      onFinish();
    }
  }

  function cancel() {
    if (abortRef.current) abortRef.current.abort();
  }

  return (
    <Card>
      <CardHeader title="Convert a document" subtitle="POST /process" />
      <CardBody className="space-y-5">
        <div>
          <input
            ref={inputRef}
            type="file"
            accept={accepted.join(',')}
            className="hidden"
            onChange={e => pick(e.target.files[0])}
          />
          <div
            onClick={() => inputRef.current && inputRef.current.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault();
              pick(e.dataTransfer.files[0]);
            }}
            className="border-2 border-dashed border-gray-300 rounded-xl px-5 py-8 text-center cursor-pointer hover:border-gray-400 hover:bg-gray-50 transition-colors"
          >
            <Icon name="mdi:tray-arrow-up" size={26} className="text-gray-400" />
            {file ? (
              <p className="mt-2 text-sm text-gray-900 font-medium">
                {file.name} <span className="text-gray-500 font-normal">({fmtBytes(file.size)})</span>
              </p>
            ) : (
              <p className="mt-2 text-sm text-gray-600">
                Drop a document here, or click to choose
              </p>
            )}
            <p className="mt-1 text-xs text-gray-400">
              {accepted.join(' · ')} — up to {fmtBytes(maxBytes)}
            </p>
          </div>

          {localError ? (
            <div className="mt-3 flex items-start gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <Icon name="mdi:alert-circle" size={16} className="mt-0.5 shrink-0" />
              <span>{localError}</span>
            </div>
          ) : null}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Output" defaultHint={defaults.output}>
            <Select value={output} onChange={e => setOutput(e.target.value)}>
              {(contract ? contract.output_choices : ['markdown', 'chunks', 'both']).map(o => (
                <option key={o} value={o}>{o}</option>
              ))}
            </Select>
          </Field>

          <Field
            label="Chunk size (max tokens)"
            help="Blank uses the service default."
            defaultHint={defaults.max_tokens}
          >
            <NumberInput
              min="1"
              placeholder={defaults.max_tokens}
              value={maxTokens}
              onChange={e => setMaxTokens(e.target.value)}
              disabled={output === 'markdown'}
            />
          </Field>

          <Field
            label="Tokenizer"
            help="Blank uses the model baked into the image."
            defaultHint={defaults.tokenizer}
          >
            <TextInput
              placeholder={defaults.tokenizer}
              value={tokenizer}
              onChange={e => setTokenizer(e.target.value)}
              disabled={output === 'markdown'}
            />
          </Field>

          <Field
            label="OCR language(s)"
            help="Comma-separated, e.g. nl,fr. Blank lets docling decide."
            defaultHint={(defaults.ocr_lang || []).join(',')}
          >
            <TextInput
              placeholder="auto"
              value={ocrLang}
              onChange={e => setOcrLang(e.target.value)}
              disabled={!doOcr}
            />
          </Field>

          <div className="sm:col-span-2 pt-1">
            <Checkbox
              label="Run OCR"
              checked={doOcr}
              onChange={setDoOcr}
              hint={`Default ${String(defaults.do_ocr)}. Turning it off is much faster on PDFs that already have a text layer, and produces nothing on scans.`}
            />
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button variant="primary" icon="mdi:play" onClick={submit} disabled={!file || running}>
            {running ? 'Converting…' : 'Convert'}
          </Button>
          {running ? (
            <Button variant="secondary" icon="mdi:close" onClick={cancel}>Cancel</Button>
          ) : null}
          {file && !running ? (
            <Button variant="muted" onClick={() => { setFile(null); setLocalError(null); }}>Clear</Button>
          ) : null}
        </div>

        {contract && contract.defaults.table_mode ? (
          <p className="text-xs text-gray-400 border-t border-gray-100 pt-3">
            Not adjustable per request: table structure{' '}
            <code className="font-mono">{String(contract.defaults.do_table_structure)}</code> in{' '}
            <code className="font-mono">{contract.defaults.table_mode}</code> mode,{' '}
            <code className="font-mono">{contract.defaults.num_threads}</code> threads.
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}

window.UploadCard = UploadCard;
