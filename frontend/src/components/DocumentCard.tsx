import { useState } from "react";
import type { Campaign, Document } from "../lib/api";
import { formatBytes, formatDate, plural } from "../lib/api";
import { Icon } from "./Icon";
import { ScenarioOrderInput } from "./ScenarioOrderInput";

const STATUS_LABEL: Record<Document["status"], string> = {
  pending: "Queued",
  processing: "Indexing…",
  ready: "Ready",
  error: "Failed",
};

export function DocumentCard({
  document: doc,
  embeddingConfigured,
  campaigns,
  onCampaignChange,
  onOrderChange,
  onOpen,
  onReindex,
  onDelete,
  onRetitle,
}: {
  document: Document;
  embeddingConfigured: boolean;
  campaigns?: Campaign[];
  onCampaignChange?: (campaignId: string | null) => void;
  onOrderChange?: (order: number) => void;
  onOpen: () => void;
  onReindex: () => void;
  onDelete: () => void;
  onRetitle: (title: string) => void;
}) {
  const [thumbFailed, setThumbFailed] = useState(false);
  const failed = doc.status === "error";
  const busy = doc.status === "pending" || doc.status === "processing";

  const rename = () => {
    const next = window.prompt("Document title", doc.title);
    if (next && next.trim() && next.trim() !== doc.title) onRetitle(next.trim());
  };

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
            {STATUS_LABEL[doc.status]}
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
          {doc.role === "campaign" && onOrderChange && (
            <ScenarioOrderInput order={doc.sort_order} onSave={onOrderChange} />
          )}
          {doc.role === "campaign" && campaigns && campaigns.length > 0 && onCampaignChange && (
            <select
              className="campaign-select"
              value={doc.campaign_id ?? ""}
              onChange={(event) => onCampaignChange(event.target.value || null)}
              onClick={(event) => event.stopPropagation()}
              title="Campaign"
            >
              <option value="">Ungrouped</option>
              {campaigns.map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  {campaign.title}
                </option>
              ))}
            </select>
          )}
        </div>
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
        <button className="icon-button" onClick={rename} title="Rename" aria-label="Rename">
          <Icon name="edit" size={17} />
        </button>
        <button
          className="icon-button"
          onClick={onReindex}
          title="Re-index"
          aria-label="Re-index"
          disabled={busy}
        >
          <Icon name="refresh" size={17} />
        </button>
        <button
          className="icon-button danger"
          onClick={onDelete}
          title="Delete"
          aria-label="Delete"
        >
          <Icon name="trash" size={17} />
        </button>
      </div>
    </article>
  );
}
