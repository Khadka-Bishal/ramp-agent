import { useCallback, useEffect, useReducer, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import {
  api,
  subscribeToEvents,
  type SessionDetail as SessionData,
  type EventDetail,
  type RunDetail,
} from "../api/client";
import EventStream from "../components/EventStream";
import ArtifactViewer from "../components/ArtifactViewer";

type Tab = "chat" | "artifacts" | "pr";

type State = {
  session: SessionData | null;
  liveEvents: EventDetail[];
  tab: Tab;
  loading: boolean;
  merging: boolean;
  chatInput: string;
  sending: boolean;
  stopping: boolean;
};

type Action =
  | { type: "setSession"; payload: SessionData | null }
  | { type: "setLoading"; payload: boolean }
  | { type: "appendLiveEvent"; payload: EventDetail }
  | { type: "setLiveEvents"; payload: EventDetail[] }
  | { type: "clearLiveEvents" }
  | { type: "setTab"; payload: Tab }
  | { type: "setMerging"; payload: boolean }
  | { type: "setChatInput"; payload: string }
  | { type: "setSending"; payload: boolean }
  | { type: "setStopping"; payload: boolean };

const initialState: State = {
  session: null,
  liveEvents: [],
  tab: "chat",
  loading: true,
  merging: false,
  chatInput: "",
  sending: false,
  stopping: false,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "setSession":
      return { ...state, session: action.payload };
    case "setLoading":
      return { ...state, loading: action.payload };
    case "appendLiveEvent":
      return { ...state, liveEvents: [...state.liveEvents, action.payload] };
    case "setLiveEvents":
      return { ...state, liveEvents: action.payload };
    case "clearLiveEvents":
      return { ...state, liveEvents: [] };
    case "setTab":
      return { ...state, tab: action.payload };
    case "setMerging":
      return { ...state, merging: action.payload };
    case "setChatInput":
      return { ...state, chatInput: action.payload };
    case "setSending":
      return { ...state, sending: action.payload };
    case "setStopping":
      return { ...state, stopping: action.payload };
    default:
      return state;
  }
}

function eventKey(
  event: Pick<EventDetail, "type" | "timestamp" | "data">,
): string {
  return `${event.type}|${event.timestamp}|${JSON.stringify(event.data || {})}`;
}

export default function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const [state, dispatch] = useReducer(reducer, initialState);
  const isMountedRef = useRef(false);
  const liveEventIdRef = useRef(-1);
  const liveEventsRef = useRef<EventDetail[]>([]);
  const sessionRequestRef = useRef(0);

  const {
    session,
    liveEvents,
    tab,
    loading,
    merging,
    chatInput,
    sending,
    stopping,
  } = state;

  const isLive = session?.status === "running";
  const latestRun = session
    ? (session.runs[session.runs.length - 1] ?? null)
    : null;

  useEffect(() => {
    liveEventsRef.current = liveEvents;
  }, [liveEvents]);

  const refreshSession = useCallback(async (sessionId: string) => {
    const requestId = ++sessionRequestRef.current;
    try {
      const updated = await api.getSession(sessionId);
      if (!isMountedRef.current || requestId !== sessionRequestRef.current) {
        return null;
      }
      dispatch({ type: "setSession", payload: updated });
      dispatch({ type: "setLoading", payload: false });
      return updated;
    } catch (error) {
      if (isMountedRef.current && requestId === sessionRequestRef.current) {
        dispatch({ type: "setLoading", payload: false });
      }
      throw error;
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!id) return;
    dispatch({ type: "setLoading", payload: true });
    dispatch({ type: "setSession", payload: null });
    dispatch({ type: "clearLiveEvents" });
    refreshSession(id).catch(() => undefined);
  }, [id, refreshSession]);

  const onEvent = useCallback(
    (event: EventDetail) => {
      if (event.type === "keepalive") return;

      const liveEvent: EventDetail = {
        ...event,
        id: liveEventIdRef.current,
      };
      liveEventIdRef.current -= 1;
      dispatch({ type: "appendLiveEvent", payload: liveEvent });
      const currentLiveEvents = [...liveEventsRef.current, liveEvent];

      if (event.type === "status_change" && id) {
        refreshSession(id)
          .then((updated) => {
            if (!updated) {
              return;
            }

            if (updated.status !== "running") {
              dispatch({ type: "clearLiveEvents" });
              return;
            }

            const dbEventKeys = new Set(updated.events.map((e) => eventKey(e)));
            dispatch({
              type: "setLiveEvents",
              payload: currentLiveEvents.filter(
                (le) => !dbEventKeys.has(eventKey(le)),
              ),
            });
          })
          .catch(() => undefined);
      }
    },
    [id, refreshSession],
  );

  useEffect(() => {
    if (!id) return;
    const source = subscribeToEvents(id, onEvent);
    return () => {
      source.close();
    };
  }, [id, onEvent]);

  const events = [...(session?.events ?? []), ...liveEvents];

  async function merge() {
    if (!id) return;
    dispatch({ type: "setMerging", payload: true });
    try {
      await api.mergeRun(id);
      await refreshSession(id);
    } catch (err) {
      console.error("Merge failed:", err);
    } finally {
      dispatch({ type: "setMerging", payload: false });
    }
  }

  async function sendMessage() {
    if (!id || !chatInput.trim() || sending) return;
    dispatch({ type: "setSending", payload: true });
    try {
      await api.sendMessage(id, chatInput.trim());
      dispatch({ type: "setChatInput", payload: "" });

      setTimeout(() => {
        window.scrollTo({
          top: document.body.scrollHeight,
          behavior: "smooth",
        });
      }, 100);
    } catch (err) {
      console.error("Send failed:", err);
    } finally {
      dispatch({ type: "setSending", payload: false });
    }
  }

  async function stopRun() {
    if (!id || stopping) return;
    dispatch({ type: "setStopping", payload: true });
    try {
      await api.stopRun(id);
      await refreshSession(id);
    } catch (err) {
      console.error("Stop failed:", err);
    } finally {
      dispatch({ type: "setStopping", payload: false });
    }
  }

  if (loading) {
    return (
      <div className="empty">
        <div className="spinner" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="empty">
        <p>Session not found.</p>
        <Link to="/" className="btn btn-outline">
          Back
        </Link>
      </div>
    );
  }

  return (
    <div className="page">
      <div style={{ marginBottom: "1.5rem" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
            marginBottom: "0.35rem",
          }}
        >
          <Link to="/" className="btn btn-ghost" aria-label="Back to sessions">
            ←
          </Link>
          <h2 style={{ fontFamily: "var(--mono)" }}>
            {extractRepo(session.repo_url)}
          </h2>
          <span className={`status status-${session.status}`}>
            <span className="status-dot" />
            {session.status}
          </span>
          {isLive ? (
            <button
              className="btn btn-danger"
              onClick={stopRun}
              disabled={stopping}
            >
              {stopping ? "Stopping…" : "Stop Agent"}
            </button>
          ) : null}
        </div>
        <p
          style={{
            color: "var(--text-2)",
            fontSize: "0.8125rem",
            maxWidth: 600,
            marginLeft: "2.75rem",
          }}
        >
          {session.prompt}
        </p>
      </div>

      <div className="tabs" role="tablist">
        {(["chat", "artifacts", "pr"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className="tab"
            onClick={() => dispatch({ type: "setTab", payload: t })}
          >
            {t === "chat" && isLive ? "● " : ""}
            {t === "chat"
              ? "Chat"
              : t === "artifacts"
                ? `Artifacts${session.artifacts.length > 0 ? ` (${session.artifacts.length})` : ""}`
                : "PR"}
          </button>
        ))}
      </div>

      <div style={{ marginTop: "1rem", flex: 1 }}>
        {tab === "chat" ? (
          <EventStream events={events} live={isLive} />
        ) : tab === "artifacts" ? (
          <ArtifactViewer
            sessionId={session.id}
            artifacts={session.artifacts}
          />
        ) : (
          <PrPanel
            run={latestRun}
            sessionStatus={session.status}
            merging={merging}
            onMerge={merge}
          />
        )}
      </div>

      {tab === "chat" && !isLive && session.status !== "pending" ? (
        <div className="chat-input-bar">
          <input
            type="text"
            className="chat-input"
            placeholder="Send a follow-up message…"
            value={chatInput}
            onChange={(e) =>
              dispatch({ type: "setChatInput", payload: e.target.value })
            }
            onKeyDown={(e) => {
              if (e.key === "Enter") sendMessage();
            }}
            disabled={sending}
          />
          <button
            className="btn btn-accent"
            onClick={sendMessage}
            disabled={sending || !chatInput.trim()}
          >
            {sending ? "…" : "↑"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function PrPanel({
  run,
  sessionStatus,
  merging,
  onMerge,
}: {
  run: RunDetail | null;
  sessionStatus: string;
  merging: boolean;
  onMerge: () => void;
}) {
  if (!run?.pr_url) {
    return (
      <div className="empty">
        <p style={{ color: "var(--text-3)" }}>
          {sessionStatus === "running"
            ? "PR will appear when the agent creates one."
            : "No PR created."}
        </p>
      </div>
    );
  }

  return (
    <div className="section">
      <div className="section-head">Pull Request</div>
      <div
        className="section-body"
        style={{ display: "flex", flexDirection: "column", gap: "0.875rem" }}
      >
        <div className="field">
          <span className="label">URL</span>
          <a href={run.pr_url} target="_blank" rel="noopener noreferrer">
            {run.pr_url} ↗
          </a>
        </div>
        {run.pr_number ? (
          <div className="field">
            <span className="label">Number</span>
            <span style={{ fontFamily: "var(--mono)" }}>#{run.pr_number}</span>
          </div>
        ) : null}
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
          <button
            className="btn btn-accent"
            onClick={onMerge}
            disabled={merging}
          >
            {merging ? "Merging…" : "Merge to Main"}
          </button>
          <a
            href={run.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline"
          >
            View on GitHub ↗
          </a>
        </div>
      </div>
    </div>
  );
}

function extractRepo(url: string): string {
  const m = url.match(/github\.com\/(.+?)(?:\.git)?$/);
  return m ? m[1] : url;
}
