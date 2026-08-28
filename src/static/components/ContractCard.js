// Rendered from GET /api/contract rather than hardcoded, so what this page
// documents is always what the running service actually enforces.
function ContractCard({ contract }) {
  const { useState } = React;
  const [open, setOpen] = useState(false);

  if (!contract) return null;
  const mb = Math.round(contract.max_upload_bytes / (1024 * 1024));

  return (
    <Card>
      <CardHeader
        title="How to use this service"
        subtitle="One endpoint. Upload a document, get markdown and chunks back on the same connection."
      >
        <Button variant="muted" icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'} onClick={() => setOpen(!open)}>
          {open ? 'Less' : 'More'}
        </Button>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
          <Fact label="Endpoint" value={contract.endpoint} mono />
          <Fact label="Request" value={contract.encoding} mono />
          <Fact label="Response" value={contract.response} mono />
          <Fact label="Max size" value={`${mb} MB per document`} />
          <Fact label="Queue" value={`${contract.max_queue_entries} entries, then 429 Busy`} />
          <Fact label="Accepts" value={contract.accepted_extensions.join(', ')} mono />
        </div>

        <p className="text-sm text-gray-600">
          The result is returned <span className="font-medium text-gray-900">in the response</span> — no
          URLs, no files on disk, nothing to poll. Progress arrives as SSE events while the
          document is converting, with a heartbeat comment every {contract.heartbeat_seconds}s so
          proxies do not drop a long conversion. Authentication: none, this is an internal service.
        </p>

        {open ? (
          <div className="space-y-4 pt-1">
            <div>
              <Label>Events</Label>
              <div className="overflow-x-auto">
                <table className="text-xs w-full">
                  <tbody className="align-top">
                    {[
                      ['queued', 'position in the queue, plus job_id. Re-sent as the queue drains.'],
                      ['processing', 'stage (converting / exporting / chunking) and progress 0–100.'],
                      ['complete', 'result.markdown, result.chunks[], result.meta. Final event.'],
                      ['error', 'message. Final event.'],
                      [': heartbeat', `comment frame every ${contract.heartbeat_seconds}s while idle.`],
                    ].map(([name, desc]) => (
                      <tr key={name} className="border-b border-gray-100 last:border-0">
                        <td className="py-1.5 pr-4 font-mono text-gray-900 whitespace-nowrap">{name}</td>
                        <td className="py-1.5 text-gray-600">{desc}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <Label>Rejections (before the stream opens)</Label>
              <ul className="text-xs text-gray-600 space-y-1 font-mono">
                <li>429 {'{"error":"Busy"}'} — queue holds {contract.max_queue_entries} entries</li>
                <li>413 — document over {mb} MB</li>
                <li>415 — type other than {contract.accepted_extensions.join(' / ')}</li>
                <li>400 — missing/empty file part, or an invalid parameter</li>
              </ul>
            </div>

            <div>
              <Label>curl</Label>
              <pre className="bg-gray-900 text-gray-100 rounded-lg p-3 text-xs overflow-x-auto">
{`curl -N -X POST ${window.location.origin}/process \\
  -F "file=@report.pdf" \\
  -F "output=both" \\
  -F "max_tokens=${contract.defaults.max_tokens}" \\
  -F "do_ocr=${contract.defaults.do_ocr}"`}
              </pre>
              <p className="text-xs text-gray-500 mt-1">
                <code className="font-mono">-N</code> disables curl's buffering, otherwise you see
                nothing until the conversion finishes.
              </p>
            </div>

            <div>
              <Label>Also available</Label>
              <ul className="text-xs text-gray-600 space-y-1">
                <li><code className="font-mono text-gray-900">GET /health</code> — liveness, queue depth, LibreOffice presence</li>
                <li><code className="font-mono text-gray-900">GET /api/queue</code> — queue state and recent job history</li>
                <li><code className="font-mono text-gray-900">GET /api/contract</code> — this contract, as JSON</li>
                <li><code className="font-mono text-gray-900">GET /docs</code> — OpenAPI</li>
              </ul>
            </div>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function Fact({ label, value, mono }) {
  return (
    <div>
      <span className="block text-xs font-medium text-gray-400 uppercase tracking-wider">{label}</span>
      <span className={cx('text-gray-900', mono && 'font-mono text-xs')}>{value}</span>
    </div>
  );
}

window.ContractCard = ContractCard;
window.Fact = Fact;
