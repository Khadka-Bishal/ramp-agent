import { useRef, useMemo, useState, useEffect } from "react";
import type { EventDetail } from "../api/client";
import ReactMarkdown from "react-markdown";

interface Props {
  events: EventDetail[];
  live?: boolean;
}

const timeFmt = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

// ── Truncate & Format ───────────────────────────────────────────────────────

function trunc(text: string | undefined, max = 600): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "\n…" : text;
}

function fmtTime(ts: string): string {
  if (!ts) return "";
  try {
    return timeFmt.format(new Date(ts));
  } catch {
    return "";
  }
}

// ── Data Types ──────────────────────────────────────────────────────────────

interface Step {
  id: number;
  type:
    | "thinking"
    | "file_read"
    | "file_write"
    | "file_create"
    | "file_delete"
    | "command"
    | "browse"
    | "status"
    | "error"
    | "sub_agent"
    | "github";
  timestamp: string;
  label: string;
  detail?: string;
  expandable: boolean;
}

interface Turn {
  id: string; // usually the ID of the user message or first event
  userMessage?: string;
  userMessageTs?: string;
  steps: Step[];
  answer?: string;
  answerTs?: string;
  isWorking: boolean;
  wasInterrupted?: boolean;
  hadError?: boolean;
}

// ── Parsing Logic ───────────────────────────────────────────────────────────

function buildTurns(events: EventDetail[], live: boolean): Turn[] {
  const turns: Turn[] = [];
  let currentTurn: Turn | undefined;
  const callIndexById = new Map<string, Step>();

  function startTurn(id: string, overrides?: Partial<Turn>) {
    currentTurn = {
      id,
      steps: [],
      isWorking: true,
      ...overrides,
    };
    turns.push(currentTurn);
  }

  for (const ev of events) {
    if (ev.type === "user_message") {
      const content = (ev.data?.content as string) || "";
      // Initial prompt usually comes before any events, or follow-ups come mapped to a new turn
      startTurn(`turn-${ev.id}`, {
        userMessage: content,
        userMessageTs: ev.timestamp,
      });
      continue;
    }

    // Ensure we have a turn (e.g., if there's no user_message event in old data)
    if (!currentTurn) {
      startTurn(`turn-initial`);
    }

    switch (ev.type) {
      case "agent_message": {
        const content = (ev.data?.content as string) || "";
        if (content.trim()) {
          currentTurn!.steps.push({
            id: ev.id,
            type: "thinking",
            timestamp: ev.timestamp,
            label: content,
            expandable: false,
          });
        }
        break;
      }

      case "tool_call": {
        const tool = ev.data?.tool as string;
        const input = ev.data?.input as Record<string, string> | undefined;
        const callId = ev.data?.id as string;

        if (tool === "complete") {
          currentTurn!.answer = input?.summary || JSON.stringify(input);
          currentTurn!.answerTs = ev.timestamp;
          currentTurn!.isWorking = false; // Turn finished!
        } else {
          let step: Step | null = null;
          if (tool === "read_file") {
            step = {
              id: ev.id,
              type: "file_read",
              timestamp: ev.timestamp,
              label: input?.path || "unknown",
              expandable: true,
            };
          } else if (tool === "write_file") {
            step = {
              id: ev.id,
              type: "file_write",
              timestamp: ev.timestamp,
              label: input?.path || "unknown",
              detail: `${(input?.content || "").length} characters written`,
              expandable: false,
            };
          } else if (tool === "create_file") {
            step = {
              id: ev.id,
              type: "file_create",
              timestamp: ev.timestamp,
              label: input?.path || "unknown",
              detail: `${(input?.content || "").length} characters`,
              expandable: false,
            };
          } else if (tool === "delete_file") {
            step = {
              id: ev.id,
              type: "file_delete",
              timestamp: ev.timestamp,
              label: input?.path || "unknown",
              expandable: false,
            };
          } else if (tool === "list_directory") {
            step = {
              id: ev.id,
              type: "browse",
              timestamp: ev.timestamp,
              label: input?.path || ".",
              expandable: true,
            };
          } else if (tool === "run_command") {
            step = {
              id: ev.id,
              type: "command",
              timestamp: ev.timestamp,
              label: input?.command || "",
              expandable: true,
            };
          } else if (tool === "run_implementer" || tool === "run_verifier") {
            step = {
              id: ev.id,
              type: "sub_agent",
              timestamp: ev.timestamp,
              label:
                tool === "run_implementer"
                  ? "Implementing changes…"
                  : "Running tests…",
              detail: tool === "run_implementer" ? input?.task : undefined,
              expandable: !!input?.task,
            };
          } else if (
            tool === "create_branch" ||
            tool === "commit_and_push" ||
            tool === "create_pr"
          ) {
            const labels: Record<string, string> = {
              create_branch: `Creating branch ${input?.branch_name || ""}`,
              commit_and_push: `Committing: ${input?.message || ""}`,
              create_pr: `Creating PR: ${input?.title || ""}`,
            };
            step = {
              id: ev.id,
              type: "github",
              timestamp: ev.timestamp,
              label: labels[tool] || tool,
              expandable: false,
            };
          }

          if (step) {
            currentTurn!.steps.push(step);
            if (callId) callIndexById.set(callId, step);
          }
        }
        break;
      }

      case "tool_result": {
        const callId = ev.data?.id as string;
        const result = ev.data?.result as string;
        if (callId && callIndexById.has(callId)) {
          const step = callIndexById.get(callId)!;
          if (result) step.detail = trunc(result);
        }
        break;
      }

      case "status_change": {
        const status = ev.data?.status as string;
        if (status === "orchestrator_completed" || status === "completed") {
          currentTurn!.isWorking = false;
        } else if (
          status === "interrupted" ||
          status === "interrupt_requested"
        ) {
          currentTurn!.isWorking = false;
          currentTurn!.wasInterrupted = true;
        } else if (
          status === "starting" ||
          status === "cloning_repo" ||
          status === "running"
        ) {
          const labels: Record<string, string> = {
            starting: "Initializing agent session...",
            cloning_repo:
              "Provisioning cloud sandbox and cloning repository (this may take a few minutes the first time)...",
            running: "Agent is evaluating the task...",
          };
          currentTurn!.steps.push({
            id: ev.id,
            type: "status",
            timestamp: ev.timestamp,
            label: labels[status] || status,
            expandable: false,
          });
        }
        break;
      }

      case "error": {
        currentTurn!.hadError = true;
        currentTurn!.steps.push({
          id: ev.id,
          type: "error",
          timestamp: ev.timestamp,
          label: (ev.data?.message as string) || "Unknown error",
          expandable: false,
        });
        currentTurn!.isWorking = false;
        break;
      }
    }
  }

  for (const turn of turns) {
    if (turn.answer || turn.isWorking || turn.wasInterrupted || turn.hadError) {
      continue;
    }
    const lastThinkingIndex = [...turn.steps]
      .map((step, index) => ({ step, index }))
      .reverse()
      .find(
        ({ step }) => step.type === "thinking" && !!step.label.trim(),
      )?.index;
    if (lastThinkingIndex === undefined) {
      continue;
    }
    const promoted = turn.steps[lastThinkingIndex];
    turn.answer = promoted.label;
    turn.answerTs = promoted.timestamp;
    turn.steps = turn.steps.filter((_, idx) => idx !== lastThinkingIndex);
  }

  // If live and last turn doesn't have an answer, mark as working
  if (
    live &&
    currentTurn &&
    !currentTurn.answer &&
    !currentTurn.steps.some((s) => s.type === "error") &&
    !currentTurn.wasInterrupted
  ) {
    currentTurn.isWorking = true;
  } else if (currentTurn && !live) {
    currentTurn.isWorking = false;
  }

  return turns;
}

const TYPE_LABELS: Record<string, string> = {
  file_read: "Read",
  file_write: "Wrote",
  file_create: "Created",
  file_delete: "Deleted",
  browse: "Listed",
  command: "Ran",
};

// ── Components ──────────────────────────────────────────────────────────────

export default function EventStream({ events, live = false }: Props) {
  const feedRef = useRef<HTMLDivElement>(null);
  const prevLen = useRef(events.length);

  const turns = useMemo(() => buildTurns(events, live), [events, live]);

  useEffect(() => {
    if (live && events.length > prevLen.current) {
      feedRef.current?.scrollTo({
        top: feedRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
    prevLen.current = events.length;
  }, [events.length, live]);

  if (turns.length === 0) {
    return (
      <div className="empty" style={{ paddingTop: "2rem" }}>
        {live ? (
          <>
            <div className="spinner" />
            <p>Waiting for agent…</p>
          </>
        ) : (
          <p>No events.</p>
        )}
      </div>
    );
  }

  return (
    <div className="feed" ref={feedRef}>
      {turns.map((turn) => (
        <TurnBlock key={turn.id} turn={turn} />
      ))}
    </div>
  );
}

function TurnBlock({ turn }: { turn: Turn }) {
  // Always default to open per user request, and do not auto-collapse when done.
  const [isOpen, setIsOpen] = useState(true);

  return (
    <div className="turn-block">
      {turn.userMessage && (
        <div className="feed-row feed-row-user">
          <div className="feed-user-bubble">{turn.userMessage}</div>
          {turn.userMessageTs && (
            <span className="feed-ts">{fmtTime(turn.userMessageTs)}</span>
          )}
        </div>
      )}

      {turn.steps.length > 0 && (
        <div className="turn-thinking-dropdown">
          <button
            className="turn-thinking-header"
            onClick={() => setIsOpen(!isOpen)}
            aria-expanded={isOpen}
          >
            <span className={`turn-chevron ${isOpen ? "open" : ""}`}>▶</span>
            <span className="turn-thinking-label">
              {turn.isWorking
                ? "Agent is thinking…"
                : "Agent finished thinking"}
            </span>
            {turn.isWorking && <span className="spinner spinner-small" />}
          </button>

          {isOpen && (
            <div className="turn-thinking-body">
              {turn.steps.map((step) => (
                <StepRow key={step.id} step={step} />
              ))}
            </div>
          )}
        </div>
      )}

      {turn.answer && (
        <div className="feed-row feed-row-full mt-4">
          <div className="feed-answer markdown-body">
            <ReactMarkdown>{turn.answer}</ReactMarkdown>
          </div>
          {turn.answerTs && (
            <span className="feed-ts">{fmtTime(turn.answerTs)}</span>
          )}
        </div>
      )}
    </div>
  );
}

function StepRow({ step }: { step: Step }) {
  const [open, setOpen] = useState(false);

  if (step.type === "error") {
    return (
      <div className="feed-row">
        <span className="feed-error">{step.label}</span>
      </div>
    );
  }

  if (step.type === "thinking") {
    return (
      <div className="feed-row">
        <div className="feed-thinking">{step.label}</div>
      </div>
    );
  }

  const prefix = TYPE_LABELS[step.type] || "";
  const hasDetail = step.expandable && !!step.detail;

  return (
    <div className="feed-row feed-row-full">
      <div className="feed-step">
        <button
          className="feed-step-head"
          onClick={() => hasDetail && setOpen(!open)}
          aria-expanded={hasDetail ? open : undefined}
          disabled={!hasDetail}
        >
          <span className="feed-step-label">
            {prefix && <span className="feed-step-prefix">{prefix} </span>}
            <span className="feed-step-path">{step.label}</span>
          </span>
          {hasDetail && (
            <span className={`feed-step-chevron ${open ? "open" : ""}`}>▸</span>
          )}
        </button>
        {open && step.detail && (
          <pre className="feed-step-detail">{step.detail}</pre>
        )}
      </div>
    </div>
  );
}
