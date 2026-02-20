import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type SessionSummary } from "../api/client";

const dtf = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export default function SessionList() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listSessions()
      .then(setSessions)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="empty">
        <div className="spinner" />
      </div>
    );
  }

  return (
    <div className="page">
      {sessions.length === 0 ? (
        <div className="empty">
          <p>No runs yet.</p>
          <p style={{ fontSize: "0.8125rem", color: "var(--text-3)" }}>
            Create a session to start the agent pipeline.
          </p>
        </div>
      ) : (
        <div className="session-grid">
          <div className="session-head">
            <span>Status</span>
            <span>Repository / Prompt</span>
            <span>PR</span>
            <span>Created</span>
          </div>
          {sessions.map((s) => (
            <Link key={s.id} to={`/sessions/${s.id}`} className="session-row">
              <span className={`status session-status status-${s.status}`}>
                <span className="status-dot" />
                {s.status}
              </span>
              <span>
                <span className="session-repo">{extractRepo(s.repo_url)}</span>
                <span className="session-prompt">{s.prompt}</span>
              </span>
              <span>
                {s.pr_url ? (
                  <a
                    className="session-pr-link"
                    href={s.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                  >
                    View PR ↗
                  </a>
                ) : (
                  <span className="session-pr-empty">—</span>
                )}
              </span>
              <span className="session-time">
                {dtf.format(new Date(s.created_at))}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function extractRepo(url: string): string {
  const m = url.match(/github\.com\/(.+?)(?:\.git)?$/);
  return m ? m[1] : url;
}
