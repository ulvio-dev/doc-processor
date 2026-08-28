function App() {
  const { useState, useEffect, useCallback, useRef } = React;
  const [contract, setContract] = useState(null);
  const [health, setHealth] = useState(null);
  const [queue, setQueue] = useState(null);
  const [connected, setConnected] = useState(false);
  const [lastError, setLastError] = useState(null);
  const [events, setEvents] = useState([]);
  const [heartbeats, setHeartbeats] = useState(0);
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);

  runningRef.current = running;

  const poll = useCallback(async () => {
    try {
      const [h, q] = await Promise.all([
        fetch('/health').then(r => r.json()),
        fetch('/api/queue').then(r => r.json()),
      ]);
      setHealth(h);
      setQueue(q);
      setConnected(true);
      setLastError(null);
    } catch (e) {
      setConnected(false);
      setLastError(e.message);
    }
  }, []);

  // The contract is static for the life of the process, so fetch it once — but
  // keep retrying while disconnected, otherwise the form never gets defaults.
  useEffect(() => {
    if (contract || !connected) return;
    fetch('/api/contract')
      .then(r => r.json())
      .then(setContract)
      .catch(() => {});
  }, [connected, contract]);

  useEffect(() => {
    poll();
    // Faster while a job is in flight, so the queue view keeps up without
    // hammering the service when nothing is happening.
    const id = setInterval(() => poll(), 2000);
    return () => clearInterval(id);
  }, [poll]);

  const onEvent = useCallback(event => {
    if (event.heartbeat) {
      setHeartbeats(n => n + 1);
      return;
    }
    setEvents(prev => [...prev, event]);
    if (event.status === 'complete') setResult(event.result);
    poll();
  }, [poll]);

  function start(setRun) {
    setRunning(setRun);
    if (setRun) {
      setEvents([]);
      setHeartbeats(0);
      setResult(null);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <StatusBar health={health} contract={contract} connected={connected} lastError={lastError} />

      <main className="flex-1 max-w-5xl w-full mx-auto px-6 py-6 space-y-5">
        <ContractCard contract={contract} />

        <UploadCard
          contract={contract}
          onEvent={onEvent}
          onFinish={poll}
          running={running}
          setRunning={start}
        />

        <RunCard events={events} running={running} heartbeats={heartbeats} />
        <ResultCard result={result} />
        <QueueCard queue={queue} />
      </main>

      <footer className="border-t border-gray-200 bg-white">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between text-xs text-gray-400">
          <span>Internal service · no authentication</span>
          <span>Powered by Ulvio</span>
        </div>
      </footer>
    </div>
  );
}

window.App = App;
