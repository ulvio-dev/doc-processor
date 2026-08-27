// GET /api/queue — live depth plus recent history. The history is bounded and
// resets with the process; it is a debugging aid, not a record.
function QueueCard({ queue }) {
  if (!queue) return null;
  const jobs = queue.jobs || [];

  return (
    <Card>
      <CardHeader
        title="Queue"
        subtitle={`${queue.queued} waiting · ${queue.processing ? '1 processing' : 'idle'} · cap ${queue.max_entries}`}
      >
        <code className="text-xs text-gray-400 font-mono hidden sm:inline">GET /api/queue</code>
      </CardHeader>
      <CardBody>
        {jobs.length === 0 ? (
          <p className="text-sm text-gray-500">No jobs yet this process.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 uppercase tracking-wider text-left">
                  <th className="pb-2 pr-4 font-medium">Job</th>
                  <th className="pb-2 pr-4 font-medium">File</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 pr-4 font-medium">Chunks</th>
                  <th className="pb-2 pr-4 font-medium">Took</th>
                  <th className="pb-2 font-medium">At</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map(job => (
                  <tr key={job.id} className="border-t border-gray-100">
                    <td className="py-2 pr-4 font-mono text-gray-500 whitespace-nowrap">{job.id}</td>
                    <td className="py-2 pr-4 text-gray-900 max-w-[14rem] truncate" title={job.filename}>
                      {job.filename}
                      <span className="text-gray-400"> · {fmtBytes(job.size_bytes)}</span>
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      <StatusTag job={job} />
                    </td>
                    <td className="py-2 pr-4 text-gray-600">
                      {job.summary ? (job.summary.chunk_count === null ? '—' : job.summary.chunk_count) : '—'}
                    </td>
                    <td className="py-2 pr-4 text-gray-600 whitespace-nowrap">
                      {fmtDuration(job.started_at, job.finished_at)}
                    </td>
                    <td className="py-2 text-gray-500 whitespace-nowrap">{fmtClock(job.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function StatusTag({ job }) {
  const tones = {
    complete: 'bg-gray-100 text-gray-700 border-gray-200',
    processing: 'bg-gray-900 text-white border-gray-900',
    queued: 'bg-white text-gray-600 border-gray-300',
    error: 'bg-red-50 text-red-700 border-red-200',
  };
  const label =
    job.status === 'queued' && job.position
      ? `queued #${job.position}`
      : job.status === 'processing' && job.stage
      ? `${job.stage} ${job.progress}%`
      : job.status;

  return (
    <span
      title={job.error || ''}
      className={cx('inline-block px-2 py-0.5 rounded-full border font-medium', tones[job.status] || tones.queued)}
    >
      {label}
    </span>
  );
}

window.QueueCard = QueueCard;
