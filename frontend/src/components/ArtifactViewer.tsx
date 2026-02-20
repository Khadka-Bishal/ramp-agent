import { useEffect, useState } from "react";
import type { ArtifactDetail } from "../api/client";
import { api } from "../api/client";
import DiffViewer from "./DiffViewer";
import ScreenshotGallery from "./ScreenshotGallery";

interface Props {
  sessionId: string;
  artifacts: ArtifactDetail[];
}

export default function ArtifactViewer({ sessionId, artifacts }: Props) {
  if (artifacts.length === 0) {
    return (
      <div className="empty">
        <p>No artifacts yet.</p>
      </div>
    );
  }

  const diffs = artifacts.filter((a) => a.type === "diff");
  const logs = artifacts.filter((a) => a.type === "log");
  const reports = artifacts.filter((a) => a.type === "report");
  const screenshots = artifacts.filter((a) => a.type === "screenshot");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {diffs.length > 0 ? (
        <section className="section">
          <div className="section-head">Changes</div>
          <div className="section-body">
            {diffs.map((a) => (
              <LazyContent key={a.id} sessionId={sessionId} artifact={a}>
                {(text) => <DiffViewer diff={text} />}
              </LazyContent>
            ))}
          </div>
        </section>
      ) : null}

      {screenshots.length > 0 ? (
        <section className="section">
          <div className="section-head">Screenshots</div>
          <div className="section-body">
            <ScreenshotGallery sessionId={sessionId} artifacts={artifacts} />
          </div>
        </section>
      ) : null}

      {logs.length > 0 ? (
        <section className="section">
          <div className="section-head">Verification Logs</div>
          <div className="section-body">
            {logs.map((a) => (
              <LazyContent key={a.id} sessionId={sessionId} artifact={a}>
                {(text) => (
                  <pre
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: "0.8125rem",
                      whiteSpace: "pre-wrap",
                      color: "var(--text-1)",
                    }}
                  >
                    {text}
                  </pre>
                )}
              </LazyContent>
            ))}
          </div>
        </section>
      ) : null}

      {reports.length > 0 ? (
        <section className="section">
          <div className="section-head">Review</div>
          <div className="section-body">
            {reports.map((a) => (
              <LazyContent key={a.id} sessionId={sessionId} artifact={a}>
                {(text) => (
                  <pre
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: "0.8125rem",
                      whiteSpace: "pre-wrap",
                      color: "var(--text-1)",
                    }}
                  >
                    {text}
                  </pre>
                )}
              </LazyContent>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function LazyContent({
  sessionId,
  artifact,
  children,
}: {
  sessionId: string;
  artifact: ArtifactDetail;
  children: (text: string) => React.ReactNode;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getArtifactContent(sessionId, artifact.id)
      .then((res) => res.text())
      .then(setContent)
      .catch(() => setContent("Failed to load"))
      .finally(() => setLoading(false));
  }, [sessionId, artifact.id]);

  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.75rem 0",
        }}
      >
        <div className="spinner" />
        <span style={{ fontSize: "0.75rem", color: "var(--text-3)" }}>
          {artifact.name}
        </span>
      </div>
    );
  }

  return <>{children(content ?? "")}</>;
}
