import { useState } from "react";
import type { Document } from "../lib/api";
import { documentStatusLabel, formatBytes, formatDate, plural } from "../lib/api";
import { Icon } from "./Icon";

export function DocumentCard({
  document: doc,
  embeddingConfigured,
  canWrite = true,
  onOpen,
  onReindex,
  onOcr,
  onDelete,
  onEdit,
}: {
  document: Document;
  embeddingConfigured: boolean;
  canWrite?: boolean;
  onOpen: () => void;
  onReindex: () => void;
  onOcr: () => void;
  onDelete: () => void;
  onEdit: () => void;
}) {
  const [thumbFailed, setThumbFailed] = useState(false);
  const failed = doc.status === "error";
  const busy = doc.status === "pending" ||
    doc.status === "processing" ||
    doc.status === "ocr";

  return (
    <article className={`document-card ${failed ? "failed" : ""}`}>
      <div className={`doc-thumb ${thumbFailed ? "fallback" : ""}`} aria-hidden="true">
        {thumbFailed ? (
          <Icon name="book" size={18} />
        ) : (
          <img
            src={doc.thumbnail_url}
            alt=""
            loading="lazy"
            onError={() => setThumbFailed(true)}
          />
        )}
      </div>
      <div className="doc-main">
        <div className="doc-title-row">
          <button className="doc-title" onClick={onOpen} title="Read this document">
            {doc.title}
          </button>
          <span className={`status-chip ${doc.status}`}>
            {busy && <span className="spinner" />}
            {documentStatusLabel(doc)}
          </span>
        </div>
        <div className="doc-meta">
          <span>{doc.original_filename}</span>
          {doc.page_count > 0 && <span>{plural(doc.page_count, "page")}</span>}
          <span>{plural(doc.chunk_count, "chunk")}</span>
          <span>{formatBytes(doc.size_bytes)}</span>
          <span>added {formatDate(doc.created_at)}</span>
          {doc.status === "ready" && embeddingConfigured && (
            <span className={doc.embedded_chunks >= doc.chunk_count ? "text-ok" : "text-warn"}>
              {doc.embedded_chunks >= doc.chunk_count
                ? "embedded"
                : `${doc.embedded_chunks}/${doc.chunk_count} embedded`}
            </span>
          )}
        </div>
        {doc.role === "campaign" && (
          <div className="doc-submeta">
            <span>{doc.campaign_title ?? "Ungrouped campaign"}</span>
            <span className="dot-sep" />
            <span>Scenario order {doc.sort_order}</span>
            {doc.file_count > 0 && (
              <>
                <span className="dot-sep" />
                <span>{plural(doc.file_count, "file")} attached</span>
              </>
            )}
          </div>
        )}
        {failed && doc.error && <p className="doc-error">{doc.error}</p>}
      </div>
      <div className="doc-actions">
        <button className="icon-button" onClick={onOpen} title="Read" aria-label="Read">
          <Icon name="book" size={17} />
        </button>
        <a
          className="icon-button"
          href={`/api/documents/${doc.id}/file${doc.page_count ? "" : "?download=true"}`}
          target="_blank"
          rel="noreferrer"
          title="Open the original file"
          aria-label="Open the original file"
        >
          <Icon name="external" size={17} />
        </a>
        {canWrite && (
          <>
            <button className="icon-button" onClick={onEdit} title="Edit document" aria-label="Edit document">
              <Icon name="edit" size={17} />
            </button>
            {!doc.is_image && (
              <button
                className="icon-button"
                onClick={onReindex}
                title="Re-index"
                aria-label="Re-index"
                disabled={busy}
              >
                <Icon name="refresh" size={17} />
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
                <Icon name="scan" size={17} />
              </button>
            )}
            <button
              className="icon-button danger"
              onClick={onDelete}
              title="Delete"
              aria-label="Delete"
            >
              <Icon name="trash" size={17} />
            </button>
          </>
        )}
      </div>
    </article>
  );
}
