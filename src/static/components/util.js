// Small shared helpers. No build step, so everything hangs off `window`.

function cx(...parts) {
  return parts.filter(Boolean).join(' ');
}

function fmtBytes(n) {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtDuration(from, to) {
  if (!from || !to) return '—';
  const s = to - from;
  return s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} s`;
}

function fmtClock(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleTimeString();
}

// Reads an SSE body off a fetch response. EventSource is not usable here:
// /process is a POST with a file body, and EventSource only does GET.
async function readSSE(response, onEvent, onHeartbeat) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let split;
    while ((split = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, split).trim();
      buffer = buffer.slice(split + 2);
      if (!block) continue;
      if (block.startsWith(':')) {          // comment frame = heartbeat
        if (onHeartbeat) onHeartbeat();
        continue;
      }
      if (!block.startsWith('data: ')) continue;
      try {
        onEvent(JSON.parse(block.slice(6)));
      } catch (e) {
        // A frame we cannot parse is worth surfacing, not swallowing.
        onEvent({ status: 'error', message: `unparseable SSE frame: ${block.slice(0, 120)}` });
      }
    }
  }
}

window.cx = cx;
window.fmtBytes = fmtBytes;
window.fmtDuration = fmtDuration;
window.fmtClock = fmtClock;
window.readSSE = readSSE;
