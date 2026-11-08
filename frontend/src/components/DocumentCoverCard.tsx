import { useState } from "react";
import type { Document } from "../lib/api";
import { plural } from "../lib/api";
import { Icon } from "./Icon";

const STATUS_LABEL: Record<Document["status"], string> = {
  pending: "Queued",
  processing: "Indexing…",
  ready: "Ready",
  error: "Failed",
};

export function DocumentCoverCard({
  document: doc,
  onOpen,
  onReindex,
  onDelete,
  onRetitle,
}: {
  document: Document;
  onOpen: () => void;
  onReindex: () => void;
  onDelete: () => void;
  onRetitle: (title: string) => void;
}) {
  const [thumbFailed, setThumbFailed] = useState(false);
  const busy = doc.status === "pending" || doc.status === "processing";
  const failed = doc.status === "error";

  const rename = () => {
    const next = window.prompt("Document title", doc.title);
    if (next && next.trim() && next.trim() !== doc.title) onRetitle(next.trim());
  };

  return (
    <article
      className={`cover-card ${doc.role === "errata" ? "errata" : ""}`}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      title={`Read ${doc.title}`}
    >
      <div className="cover-frame">
        {thumbFailed ? (
          <div className="cover-placeholder">
            <Icon name="book" size={30} />
            <span>{doc.title}</span>
          </div>
        ) : (
          <img
            src={doc.thumbnail_url}
            alt={`Cover of ${doc.title}`}
            loading="lazy"
            onError={() => setThumbFailed(true)}
          />
        )}
        <div className="cover-shade" />

        <div className="cover-top">
          <div className="cover-actions" onClick={(event) => event.stopPropagation()}>
            <a
              className="icon-button"
              href={`/api/documents/${doc.id}/file`}
              target="_blank"
              rel="noreferrer"
              title="Open the original file"
              aria-label="Open the original file"
            >
              <Icon name="external" size={15} />
            </a>
            <button className="icon-button" onClick={rename} title="Rename" aria-label="Rename">
              <Icon name="edit" size={15} />
            </button>
            <button
              className="icon-button"
              onClick={onReindex}
              disabled={busy}
              title="Re-index"
              aria-label="Re-index"
            >
              <Icon name="refresh" size={15} />
            </button>
            <button
              className="icon-button danger"
              onClick={onDelete}
              title="Delete"
              aria-label="Delete"
            >
              <Icon name="trash" size={15} />
            </button>
          </div>
        </div>

        <div className="cover-info">
          {doc.status !== "ready" && (
            <span className={`status-chip cover-status ${doc.status}`}>
              {busy && <span className="spinner" />}
              {STATUS_LABEL[doc.status]}
            </span>
          )}
          <h3>{doc.title}</h3>
          <p>
            {doc.page_count ? `${plural(doc.page_count, "page")} · ` : ""}
            {plural(doc.chunk_count, "chunk")}
          </p>
          {failed && <p className="cover-error">Indexing failed</p>}
        </div>
      </div>
    </article>
  );
}
