import { useState } from "react";
import type { Document } from "../lib/api";
import { documentStatusLabel, plural } from "../lib/api";
import { Icon } from "./Icon";

export function DocumentCoverCard({
  document: doc,
  canWrite = true,
  onOpen,
  onReindex,
  onOcr,
  onDelete,
  onEdit,
}: {
  document: Document;
  canWrite?: boolean;
  onOpen: () => void;
  onReindex: () => void;
  onOcr: () => void;
  onDelete: () => void;
  onEdit: () => void;
}) {
  const [thumbFailed, setThumbFailed] = useState(false);
  const busy = doc.status === "pending" ||
    doc.status === "processing" ||
    doc.status === "ocr";
  const failed = doc.status === "error";

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
            {canWrite && (
              <>
                <button className="icon-button" onClick={onEdit} title="Edit document" aria-label="Edit document">
                  <Icon name="edit" size={15} />
                </button>
                {!doc.is_image && (
                  <button
                    className="icon-button"
                    onClick={onReindex}
                    disabled={busy}
                    title="Re-index"
                    aria-label="Re-index"
                  >
                    <Icon name="refresh" size={15} />
                  </button>
                )}
                {doc.can_ocr && (
                  <button
                    className="icon-button"
                    onClick={onOcr}
                    disabled={busy}
                    title={
                      doc.status === "ocr"
                        ? "OCR running"
                        : doc.ocr_requested
                          ? "OCR queued"
                          : "Run OCR on this document"
                    }
                    aria-label="Run OCR"
                  >
                    <Icon name="scan" size={15} />
                  </button>
                )}
                <button
                  className="icon-button danger"
                  onClick={onDelete}
                  title="Delete"
                  aria-label="Delete"
                >
                  <Icon name="trash" size={15} />
                </button>
              </>
            )}
          </div>
        </div>

        <div className="cover-info">
          {doc.role === "campaign" && (
            <p className="cover-submeta">
              {doc.campaign_title ?? "Ungrouped campaign"} · Scenario order {doc.sort_order}
              {doc.file_count ? ` · ${plural(doc.file_count, "file")}` : ""}
            </p>
          )}
          {doc.status !== "ready" && (
            <span className={`status-chip cover-status ${doc.status}`}>
              {busy && <span className="spinner" />}
              {documentStatusLabel(doc)}
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
