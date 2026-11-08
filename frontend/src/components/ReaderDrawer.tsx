import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Icon } from "./Icon";

export interface ReaderTarget {
  documentId: string;
  title: string;
  page: number | null;
  gameTitle?: string;
  roleLabel?: string;
}

interface PagePayload {
  page: number;
  total_pages: number;
  chunks: { id: number; text: string }[];
}

export function ReaderDrawer({
  target,
  onClose,
}: {
  target: ReaderTarget | null;
  onClose: () => void;
}) {
  const [page, setPage] = useState<PagePayload | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const documentId = target?.documentId ?? null;
  const targetPage = target?.page ?? 1;

  useEffect(() => {
    setPageNumber(targetPage);
  }, [documentId, targetPage]);

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .page(documentId, pageNumber)
      .then((payload) => {
        if (!cancelled) setPage(payload);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, pageNumber]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!target || !documentId) return null;

  return (
    <div className="drawer-layer">
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" aria-label="Document reader">
        <header className="drawer-head">
          <div>
            {target.gameTitle && <p className="eyebrow">{target.gameTitle}</p>}
            <h3>{target.title}</h3>
            <p className="drawer-sub">
              {target.roleLabel ? `${target.roleLabel} · ` : ""}
              page {pageNumber}
              {page?.total_pages ? ` of ${page.total_pages}` : ""}
            </p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close reader">
            <Icon name="close" size={19} />
          </button>
        </header>

        <div className="drawer-body">
          {loading && (
            <p className="thinking">
              <span className="spinner" /> Loading page…
            </p>
          )}
          {error && <p className="text-danger">{error}</p>}
          {!loading &&
            page?.chunks.map((chunk) => (
              <p className="reader-text" key={chunk.id}>
                {chunk.text}
              </p>
            ))}
          {!loading && !error && page?.chunks.length === 0 && (
            <p className="fine-print">
              This page has no indexed text (it may be blank or contain only artwork).
            </p>
          )}
        </div>

        <footer className="drawer-foot">
          <button
            className="button ghost small"
            onClick={() => setPageNumber((value) => Math.max(1, value - 1))}
            disabled={pageNumber <= 1}
            title="Previous page"
          >
            <Icon name="arrow-left" size={15} /> Prev
          </button>
          <span className="drawer-page">p. {pageNumber}</span>
          <button
            className="button ghost small"
            onClick={() => setPageNumber((value) => value + 1)}
            disabled={!page?.total_pages || pageNumber >= page.total_pages}
            title="Next page"
          >
            Next <Icon name="chevron" size={15} />
          </button>
          <span className="drawer-spacer" />
          <a
            className="button ghost small"
            href={api.fileUrl(documentId, pageNumber)}
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="external" size={15} /> Original
          </a>
          <a className="button ghost small" href={api.fileUrl(documentId, null, true)}>
            <Icon name="download" size={15} />
          </a>
        </footer>
      </aside>
    </div>
  );
}
