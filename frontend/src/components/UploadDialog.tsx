import { useRef, useState } from "react";
import {
  api,
  formatBytes,
  type Campaign,
  type FormatInfo,
  type Game,
  type GameType,
} from "../lib/api";
import { Modal } from "./Modal";
import { Icon } from "./Icon";

interface QueueItem {
  id: number;
  file: File;
  status: "queued" | "uploading" | "done" | "error";
  error?: string;
}

let nextId = 1;

export function UploadDialog({
  game,
  gameType,
  formats,
  campaigns,
  initialRole,
  initialCampaignId,
  onClose,
  onUploaded,
  notify,
}: {
  game: Game;
  gameType: GameType | undefined;
  formats: FormatInfo[];
  campaigns: Campaign[];
  initialRole: string;
  initialCampaignId?: string | null;
  onClose: () => void;
  onUploaded: () => void;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const [role, setRole] = useState(initialRole);
  const [campaignId, setCampaignId] = useState(initialCampaignId ?? "");
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rejected, setRejected] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const allowed = new Set(formats.flatMap((format) => format.extensions));
  const roles = gameType?.roles ?? [{ id: "core", label: "Core rules" }];

  const addFiles = (files: FileList | File[]) => {
    const accepted: QueueItem[] = [];
    const refused: string[] = [];
    for (const file of Array.from(files)) {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!allowed.has(ext)) {
        refused.push(file.name);
        continue;
      }
      accepted.push({ id: nextId++, file, status: "queued" });
    }
    setQueue((current) => [...current, ...accepted]);
    setRejected(refused);
  };

  const remove = (id: number) => {
    setQueue((current) => current.filter((item) => item.id !== id));
  };

  const upload = async () => {
    const pending = queue.filter((item) => item.status === "queued");
    if (!pending.length) return;
    setBusy(true);
    for (const item of pending) {
      setQueue((current) =>
        current.map((entry) => (entry.id === item.id ? { ...entry, status: "uploading" } : entry)),
      );
      try {
        await api.uploadDocument(
          game.id,
          role,
          item.file,
          undefined,
          role === "campaign" ? campaignId || null : null,
        );
        setQueue((current) =>
          current.map((entry) => (entry.id === item.id ? { ...entry, status: "done" } : entry)),
        );
        onUploaded();
      } catch (err) {
        const message = (err as Error).message;
        setQueue((current) =>
          current.map((entry) =>
            entry.id === item.id ? { ...entry, status: "error", error: message } : entry,
          ),
        );
        notify(`${item.file.name}: ${message}`, "error");
      }
    }
    setBusy(false);
    notify("Uploads finished. Indexing continues in the background.", "ok");
  };

  const pendingCount = queue.filter((item) => item.status === "queued").length;
  const doneCount = queue.filter((item) => item.status === "done").length;

  return (
    <Modal
      title={`Add documents to ${game.title}`}
      subtitle="The core rules are the primary source; supplements and campaigns are filed alongside."
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
      footer={
        <>
          <span className="modal-foot-note">
            {doneCount > 0 ? `${doneCount} uploaded` : `${queue.length} file(s) queued`}
          </span>
          <button className="button ghost" onClick={onClose} disabled={busy}>
            {doneCount > 0 ? "Done" : "Cancel"}
          </button>
          <button
            className="button primary"
            onClick={upload}
            disabled={busy || pendingCount === 0}
          >
            {busy ? <span className="spinner light" /> : <Icon name="upload" size={16} />}
            Upload {pendingCount > 0 ? pendingCount : ""}
          </button>
        </>
      }
    >
      <label className="field">
        <span>File these under</span>
        <select value={role} onChange={(event) => setRole(event.target.value)} disabled={busy}>
          {roles.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.label}
            </option>
          ))}
        </select>
      </label>

      {role === "campaign" && (
        <label className="field">
          <span>Campaign</span>
          <select
            value={campaignId}
            onChange={(event) => setCampaignId(event.target.value)}
            disabled={busy}
          >
            <option value="">Ungrouped campaign document</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.title}
              </option>
            ))}
          </select>
          {campaigns.length === 0 && (
            <small className="fine-print">
              Create a campaign from the game view first to file this scenario.
            </small>
          )}
        </label>
      )}

      <div
        className={`dropzone ${dragging ? "dragging" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
      >
        <Icon name="upload" size={24} />
        <strong>Drop files here or click to browse</strong>
        <span>
          {formats.map((format) => `.${format.extensions.join(", .")}`).join(" · ")}
        </span>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </div>

      {rejected.length > 0 && (
        <p className="form-error">
          Unsupported: {rejected.join(", ")}. Convert them to PDF first.
        </p>
      )}

      {queue.length > 0 && (
        <ul className="upload-list">
          {queue.map((item) => (
            <li key={item.id} className={item.status}>
              <Icon
                name={item.status === "done" ? "check" : item.status === "error" ? "alert" : "book"}
                size={16}
              />
              <div className="upload-info">
                <span>{item.file.name}</span>
                <small>{formatBytes(item.file.size)}</small>
                {item.error && <small className="text-danger">{item.error}</small>}
              </div>
              {item.status === "uploading" && <span className="spinner" />}
              {item.status === "queued" && !busy && (
                <button
                  className="icon-button small"
                  onClick={() => remove(item.id)}
                  aria-label="Remove"
                >
                  <Icon name="close" size={15} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="fine-print">
        Scanned PDFs need a text layer; run OCR first. Indexing happens in the background — you
        can keep using the app.
      </p>
    </Modal>
  );
}
