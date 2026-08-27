// The header. This is the "is anything wrong?" line: connection, queue depth,
// and the environment facts that explain the failures you are most likely to
// hit (LibreOffice missing => .doc uploads fail).
function StatusBar({ health, contract, connected, lastError }) {
  const busy = health && health.queued + (health.processing ? 1 : 0) >= (contract ? contract.max_queue_entries : 10);

  return (
    <div className="border-b border-gray-200 bg-white">
      <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between gap-6 flex-wrap">
        <div className="flex items-center gap-3">
          <Icon name="mdi:file-document-outline" size={22} className="text-gray-900" />
          <div>
            <h1 className="text-base font-semibold text-gray-900 leading-tight">Doc Processor</h1>
            <p className="text-xs text-gray-500">PDF / DOCX / DOC → markdown + chunks</p>
          </div>
        </div>

        <div className="flex items-center gap-5 text-sm">
          <Pill
            ok={connected}
            label={connected ? 'Connected' : 'Not connected'}
            icon={connected ? 'mdi:check-circle' : 'mdi:alert-circle'}
          />

          <div className="flex items-center gap-1.5 text-gray-600">
            <Icon name="mdi:tray-full" size={16} className="text-gray-400" />
            <span>
              queue{' '}
              <span className={cx('font-semibold', busy ? 'text-red-700' : 'text-gray-900')}>
                {health ? health.queued : '—'}
              </span>
              {contract ? <span className="text-gray-400"> / {contract.max_queue_entries}</span> : null}
            </span>
            {health && health.processing ? (
              <span className="ml-1 text-xs text-gray-500">(1 processing)</span>
            ) : null}
          </div>
        </div>
      </div>

      {!connected ? (
        <Banner
          icon="mdi:lan-disconnect"
          title="Cannot reach the service"
          detail={
            lastError
              ? `${lastError} — is the container running, and is /health reachable from this page?`
              : 'is the container running, and is /health reachable from this page?'
          }
        />
      ) : null}

      {connected && health && health.libreoffice === false ? (
        <Banner
          icon="mdi:alert-outline"
          tone="warn"
          title="LibreOffice is not installed — legacy .doc uploads will fail"
          detail="docling converts .doc to .docx by shelling out to `soffice`. .pdf and .docx are unaffected."
        />
      ) : null}

      {connected && busy ? (
        <Banner
          icon="mdi:tray-full"
          tone="warn"
          title="Queue is full — new uploads are being rejected with 429 Busy"
          detail="Wait for the queue to drain; the service accepts work again as soon as a slot frees up."
        />
      ) : null}
    </div>
  );
}

function Pill({ ok, label, icon }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
        ok ? 'bg-gray-100 text-gray-800 border-gray-200' : 'bg-red-50 text-red-700 border-red-200'
      )}
    >
      <Icon name={icon} size={14} />
      {label}
    </span>
  );
}

function Banner({ icon, title, detail, tone = 'error' }) {
  const tones = {
    error: 'bg-red-50 border-red-200 text-red-800',
    warn: 'bg-gray-100 border-gray-200 text-gray-800',
  };
  return (
    <div className={cx('border-t px-6 py-3', tones[tone])}>
      <div className="max-w-5xl mx-auto flex items-start gap-2.5 text-sm">
        <Icon name={icon} size={17} className="mt-0.5 shrink-0" />
        <div>
          <p className="font-medium">{title}</p>
          {detail ? <p className="text-xs mt-0.5 opacity-90">{detail}</p> : null}
        </div>
      </div>
    </div>
  );
}

window.StatusBar = StatusBar;
window.Banner = Banner;
