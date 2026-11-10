import type { Document } from "../lib/api";
import { formatBytes, plural } from "../lib/api";
import { DocumentCard } from "./DocumentCard";
import { DocumentCoverCard } from "./DocumentCoverCard";
import { Icon } from "./Icon";

const STATUS_LABEL: Record<Document["status"], string> = {
  pending: "Queued",
  processing: "Indexing…",
  ocr: "Running OCR…",
  ready: "Ready",
  error: "Failed",
  unindexed: "Not indexed",
};

/**
 * One scenario inside a campaign: a lead document plus any extra files
 * (maps, handouts, card decks) that belong to it.
 */
export function ScenarioGroup({
  lead,
  files,
  view,
  embeddingConfigured,
  canWrite = true,
  onOpenDoc,
  onReindexDoc,
  onOcrDoc,
  onDeleteDoc,
  onEditDoc,
  onAddFile,
}: {
  lead: Document;
  files: Document[];
  view: "grid" | "list";
  embeddingConfigured: boolean;
  canWrite?: boolean;
  onOpenDoc: (doc: Document) => void;
  onReindexDoc: (doc: Document) => void;
  onOcrDoc: (doc: Document) => void;
  onDeleteDoc: (doc: Document) => void;
  onEditDoc: (doc: Document) => void;
  onAddFile: () => void;
}) {
  const ordered = [...files].sort(
    (a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title),
  );

  return (
    <article className={`scenario ${ordered.length ? "has-files" : ""}`}>
      {view === "grid" ? (
        <DocumentCoverCard
          document={lead}
          canWrite={canWrite}
          onOpen={() => onOpenDoc(lead)}
          onReindex={() => onReindexDoc(lead)}
          onOcr={() => onOcrDoc(lead)}
          onDelete={() => onDeleteDoc(lead)}
          onEdit={() => onEditDoc(lead)}
        />
      ) : (
        <DocumentCard
          document={lead}
          embeddingConfigured={embeddingConfigured}
          canWrite={canWrite}
          onOpen={() => onOpenDoc(lead)}
          onReindex={() => onReindexDoc(lead)}
          onOcr={() => onOcrDoc(lead)}
          onDelete={() => onDeleteDoc(lead)}
          onEdit={() => onEditDoc(lead)}
        />
      )}

      {ordered.length > 0 && (
        <ul className="scenario-files" aria-label={`Files in ${lead.title}`}>
          {ordered.map((file) => {
            const busy = file.status === "pending" ||
      file.status === "processing" ||
      file.status === "ocr";
            return (
              <li key={file.id} className={`scenario-file ${file.status}`}>
                <span className="scenario-file-icon" aria-hidden="true">
                  <Icon name={file.is_image ? "image" : "book"} size={15} />
                </span>
                <div className="scenario-file-body">
                  <button
                    className="scenario-file-title"
                    onClick={() => onOpenDoc(file)}
                    title={`Read ${file.title}`}
                  >
                    {file.title}
                  </button>
                  <span className="scenario-file-meta">
                    {file.original_filename}
                    {file.page_count ? ` · ${plural(file.page_count, "page")}` : ""}
                    {` · ${formatBytes(file.size_bytes)}`}
                  </span>
                </div>
                {file.status !== "ready" && (
                  <span className={`status-chip ${file.status}`}>
                    {busy && <span className="spinner" />}
                    {STATUS_LABEL[file.status]}
                  </span>
                )}
                <div className="scenario-file-actions">
                  <a
                    className="icon-button small"
                    href={`/api/documents/${file.id}/file`}
                    target="_blank"
                    rel="noreferrer"
                    title="Open the original file"
                    aria-label="Open the original file"
                  >
                    <Icon name="external" size={15} />
                  </a>
                  {canWrite && (
                    <>
                      <button
                        className="icon-button small"
                        onClick={() => onEditDoc(file)}
                        title="Edit file"
                        aria-label="Edit file"
                      >
                        <Icon name="edit" size={15} />
                      </button>
                      {file.can_ocr && (
                        <button
                          className="icon-button small"
                          onClick={() => onOcrDoc(file)}
                          title="Run OCR on this file"
                          aria-label="Run OCR"
                        >
                          <Icon name="scan" size={15} />
                        </button>
                      )}
                      {!file.is_image && (
                        <button
                          className="icon-button small"
                          onClick={() => onReindexDoc(file)}
                          disabled={busy}
                          title="Re-index"
                          aria-label="Re-index"
                        >
                          <Icon name="refresh" size={15} />
                        </button>
                      )}
                      <button
                        className="icon-button small danger"
                        onClick={() => onDeleteDoc(file)}
                        title="Remove file"
                        aria-label="Remove file"
                      >
                        <Icon name="trash" size={15} />
                      </button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {canWrite && (
        <button className="scenario-add" onClick={onAddFile}>
          <Icon name="plus" size={14} />
          Add file
        </button>
      )}
    </article>
  );
}
