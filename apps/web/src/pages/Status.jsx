import { useCallback, useEffect, useMemo, useState } from "react";

function Status() {
  const apiBaseUrl = useMemo(
    () => import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
    []
  );
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);

  const fetchStatus = useCallback(async () => {
    setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/health`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      setData(payload);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch status");
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    fetchStatus();
    const intervalId = window.setInterval(fetchStatus, 10000);
    return () => window.clearInterval(intervalId);
  }, [fetchStatus]);

  const statusTone =
    data?.status === "ok" && data?.temporal === "connected"
      ? "healthy"
      : error
        ? "error"
        : "degraded";

  return (
    <section className="panel">
      <div className="panel-head">
        <h1>System Status</h1>
        <button type="button" className="btn" onClick={fetchStatus}>
          Refresh
        </button>
      </div>

      <p className="muted">
        Live check against <span className="mono">{apiBaseUrl}/health</span>
      </p>

      {loading ? (
        <p>Loading status...</p>
      ) : (
        <article className="status-card">
          <div className={`badge badge-${statusTone}`}>
            {statusTone.toUpperCase()}
          </div>
          <dl>
            <dt>API status</dt>
            <dd>{data?.status || "unknown"}</dd>
            <dt>Temporal connection</dt>
            <dd>{data?.temporal || "unknown"}</dd>
            <dt>Last updated</dt>
            <dd>{lastUpdated ? lastUpdated.toLocaleTimeString() : "n/a"}</dd>
          </dl>
          {error ? <p className="error-text">Error: {error}</p> : null}
        </article>
      )}
    </section>
  );
}

export default Status;
