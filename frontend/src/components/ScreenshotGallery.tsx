import { useState } from "react";
import type { ArtifactDetail } from "../api/client";

interface Props {
  sessionId: string;
  artifacts: ArtifactDetail[];
}

export default function ScreenshotGallery({ sessionId, artifacts }: Props) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const screenshots = artifacts.filter((a) => a.type === "screenshot");

  if (screenshots.length === 0) {
    return (
      <div className="empty">
        <p>No screenshots.</p>
      </div>
    );
  }

  return (
    <>
      <div className="shots">
        {screenshots.map((ss) => {
          const src = `/api/sessions/${sessionId}/artifacts/${ss.id}/content`;
          const route = (ss.metadata?.route as string) ?? ss.name;
          return (
            <button
              key={ss.id}
              type="button"
              className="shot"
              onClick={() => setLightboxSrc(src)}
              aria-label={`View screenshot of ${route}`}
            >
              <img
                src={src}
                alt={`Screenshot of ${route}`}
                width={560}
                height={315}
                loading="lazy"
              />
              <div className="shot-label">{route}</div>
            </button>
          );
        })}
      </div>

      {lightboxSrc ? (
        <button
          type="button"
          className="lightbox"
          onClick={() => setLightboxSrc(null)}
          aria-label="Close screenshot preview"
        >
          <img src={lightboxSrc} alt="Full-size screenshot" />
        </button>
      ) : null}
    </>
  );
}
