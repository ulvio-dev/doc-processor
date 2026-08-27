// The parsed document. Markdown is shown as-is rather than rendered: the point
// is to inspect what the service actually produced, not to make it look nice.
function ResultCard({ result }) {
  const { useState } = React;
  const [tab, setTab] = useState('markdown');

  if (!result) return null;

  const meta = result.meta || {};
  const hasMarkdown = typeof result.markdown === 'string';
  const hasChunks = Array.isArray(result.chunks);
  const active = tab === 'markdown' && !hasMarkdown ? 'chunks' : tab;

  function copy(text) {
    navigator.clipboard.writeText(text);
  }

  return (
    <Card>
      <CardHeader title="Result" subtitle={meta.filename}>
        <Button
          variant="secondary"
          icon="mdi:content-copy"
          onClick={() =>
            copy(active === 'markdown' ? result.markdown : JSON.stringify(result.chunks, null, 2))
          }
        >
          Copy
        </Button>
      </CardHeader>

      <CardBody className="space-y-4">
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <Fact label="Format" value={meta.format || '—'} mono />
          <Fact label="Size" value={fmtBytes(meta.size_bytes)} />
          <Fact label="Pages" value={meta.pages || '—'} />
          <Fact label="Chunks" value={hasChunks ? result.chunks.length : '—'} />
          <Fact label="Markdown" value={hasMarkdown ? `${result.markdown.length} chars` : '—'} />
        </div>

        <div className="flex gap-1 border-b border-gray-200">
          {[
            ['markdown', 'Markdown', hasMarkdown],
            ['chunks', `Chunks${hasChunks ? ` (${result.chunks.length})` : ''}`, hasChunks],
            ['meta', 'Meta', true],
          ].map(([key, label, enabled]) => (
            <button
              key={key}
              disabled={!enabled}
              onClick={() => setTab(key)}
              className={cx(
                'px-3 py-2 text-sm font-medium -mb-px border-b-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
                active === key
                  ? 'border-gray-900 text-gray-900'
                  : 'border-transparent text-gray-500 hover:text-gray-900'
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {active === 'markdown' && hasMarkdown ? (
          <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-xs whitespace-pre-wrap break-words max-h-[28rem] overflow-y-auto font-mono text-gray-800">
            {result.markdown || '(empty)'}
          </pre>
        ) : null}

        {active === 'chunks' && hasChunks ? (
          <div className="space-y-2 max-h-[28rem] overflow-y-auto">
            {result.chunks.length === 0 ? (
              <p className="text-sm text-gray-500">No chunks produced.</p>
            ) : (
              result.chunks.map((chunk, i) => (
                <div key={i} className="border border-gray-200 rounded-lg overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-1.5 bg-gray-50 border-b border-gray-200">
                    <span className="text-xs font-mono text-gray-500">chunk {i}</span>
                    <span className="text-xs text-gray-400">{chunk.length} chars</span>
                  </div>
                  <p className="px-3 py-2 text-xs text-gray-800 whitespace-pre-wrap break-words">
                    {chunk}
                  </p>
                </div>
              ))
            )}
          </div>
        ) : null}

        {active === 'meta' ? (
          <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-xs overflow-x-auto font-mono text-gray-800">
            {JSON.stringify(meta, null, 2)}
          </pre>
        ) : null}
      </CardBody>
    </Card>
  );
}

window.ResultCard = ResultCard;
