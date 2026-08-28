// Live view of the current run: where it is in the queue, what stage it is at,
// and every event received. Errors are shown verbatim — this page is meant to
// be the first place you look, so it must not soften what the service said.
function RunCard({ events, running, heartbeats }) {
  if (!events.length) return null;

  const data = events.filter(e => !e.heartbeat);
  const latest = data[data.length - 1] || {};
  const error = data.find(e => e.status === 'error');
  const queued = latest.status === 'queued' ? latest : null;
  const progress =
    latest.status === 'complete'
      ? 100
      : data.reduce((acc, e) => (typeof e.progress === 'number' ? e.progress : acc), 0);

  return (
    <Card>
      <CardHeader
        title="Run"
        subtitle={
          error
            ? 'Failed'
            : latest.status === 'complete'
            ? 'Complete'
            : queued
            ? `Waiting in queue — position ${queued.position}`
            : `Processing — ${latest.stage || 'starting'}`
        }
      >
        {latest.job_id ? (
          <code className="text-xs text-gray-400 font-mono">{latest.job_id}</code>
        ) : null}
      </CardHeader>
      <CardBody className="space-y-4">
        {error ? (
          <div className="flex items-start gap-2.5 text-sm text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-3">
            <Icon name="mdi:alert-circle" size={18} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">The service reported an error</p>
              <p className="font-mono text-xs mt-1 break-all">{error.message}</p>
            </div>
          </div>
        ) : (
          <div>
            <div className="flex items-center justify-between text-xs text-gray-500 mb-1.5">
              <span>{queued ? `queued (position ${queued.position})` : latest.stage || 'starting'}</span>
              <span>{progress}%</span>
            </div>
            <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-gray-900 transition-all duration-300"
                style={{ width: `${queued ? 0 : progress}%` }}
              />
            </div>
          </div>
        )}

        <details className="text-xs">
          <summary className="cursor-pointer text-gray-500 hover:text-gray-900 select-none">
            {data.length} event{data.length === 1 ? '' : 's'}
            {heartbeats ? ` · ${heartbeats} heartbeat${heartbeats === 1 ? '' : 's'}` : ''}
          </summary>
          <div className="mt-2 space-y-1 max-h-56 overflow-y-auto font-mono text-gray-600">
            {data.map((e, i) => (
              <div key={i} className="flex gap-2">
                <span className="text-gray-400 shrink-0">{String(i).padStart(2, '0')}</span>
                <span className="break-all">
                  {e.status}
                  {e.position ? ` position=${e.position}` : ''}
                  {e.stage ? ` stage=${e.stage}` : ''}
                  {typeof e.progress === 'number' ? ` progress=${e.progress}` : ''}
                  {e.message ? ` message=${e.message}` : ''}
                </span>
              </div>
            ))}
            {running ? <div className="text-gray-400">…streaming</div> : null}
          </div>
        </details>
      </CardBody>
    </Card>
  );
}

window.RunCard = RunCard;
