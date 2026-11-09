import { useRef, useState } from "react";
import {
  api,
  formatBytes,
  type Campaign,
  type Document,
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
  progress?: number;
  error?: string;
}

let nextId = 1;

/** Above this, upload in chunks so proxy request limits do not apply. */
const CHUNKED_THRESHOLD = 64 * 1024 * 1024;

export function UploadDialog({
  game,
  gameType,
  formats,
  maxUploadMb,
  campaigns,
  documents = [],
  initialRole,
  initialCampaignId,
  initialScenarioId,
  onClose,
  onUploaded,
  notify,
}: {
  game: Game;
  gameType: GameType | undefined;
  formats: FormatInfo[];
  maxUploadMb: number;
  campaigns: Campaign[];
  documents?: Document[];
  initialRole: string;
  initialCampaignId?: string | null;
  initialScenarioId?: string | null;
  onClose: () => void;
  onUploaded: () => void;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const [role, setRole] = useState(initialRole);
  const [campaignId, setCampaignId] = useState(initialCampaignId ?? "");
  const [scenarioId, setScenarioId] = useState(initialScenarioId ?? "");
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rejected, setRejected] = useState<string[]>([]);
  const [tooLarge, setTooLarge] = useState<string[]>([]);
  const [groupFiles, setGroupFiles] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);

  const lockedScenario = initialScenarioId
    ? documents.find((doc) => doc.id === initialScenarioId) ?? null
    : null;
  const scenarioOptions = documents.filter(
    (doc) =>
      doc.role === "campaign" &&
      !doc.scenario_id &&
      (doc.campaign_id ?? "") === campaignId,
  );

  const allowed = new Set(formats.flatMap((format) => format.extensions));
  const roles = gameType?.roles ?? [{ id: "core", label: "Core rules" }];

  const addFiles = (files: FileList | File[]) => {
    const accepted: QueueItem[] = [];
    const refused: string[] = [];
    const oversized: string[] = [];
    const limit = maxUploadMb * 1024 * 1024;
    for (const file of Array.from(files)) {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!allowed.has(ext)) {
        refused.push(file.name);
        continue;
      }
      if (file.size > limit) {
        oversized.push(`${file.name} (${formatBytes(file.size)})`);
        continue;
      }
      accepted.push({ id: nextId++, file, status: "queued" });
    }
    setQueue((current) => [...current, ...accepted]);
    setRejected(refused);
    setTooLarge(oversized);
  };

  const remove = (id: number) => {
    setQueue((current) => current.filter((item) => item.id !== id));
  };

  const upload = async () => {
    const pending = queue.filter((item) => item.status === "queued");
    if (!pending.length) return;
    setBusy(true);
    let targetScenario = lockedScenario?.id ?? (role === "campaign" ? scenarioId || null : null);
    for (const item of pending) {
      setQueue((current) =>
        current.map((entry) => (entry.id === item.id ? { ...entry, status: "uploading" } : entry)),
      );
      try {
        const uploadOptions = {
          campaignId: role === "campaign" ? campaignId || null : null,
          scenarioId: targetScenario,
        };
        const created =
          item.file.size > CHUNKED_THRESHOLD
            ? await api.uploadDocumentChunked(game.id, role, item.file, {
                ...uploadOptions,
                onProgress: (fraction) =>
                  setQueue((current) =>
                    current.map((entry) =>
                      entry.id === item.id ? { ...entry, progress: fraction } : entry,
                    ),
                  ),
              })
            : await api.uploadDocument(
                game.id,
                role,
                item.file,
                undefined,
                uploadOptions.campaignId,
                uploadOptions.scenarioId,
              );
        if (role === "campaign" && groupFiles && !targetScenario) {
          // The first file becomes the scenario the rest are filed under.
          targetScenario = created.id;
        }
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
    const indexedFormats = new Set(
      formats.filter((format) => format.indexed).flatMap((format) => format.extensions),
    );
    const anyIndexed = pending.some((item) =>
      indexedFormats.has(item.file.name.split(".").pop()?.toLowerCase() ?? ""),
    );
    notify(
      anyIndexed
        ? "Uploads finished. Indexing continues in the background."
        : "Uploads finished. Images are stored and previewed, but not indexed.",
      "ok",
    );
  };

  const pendingCount = queue.filter((item) => item.status === "queued").length;
  const doneCount = queue.filter((item) => item.status === "done").length;

  return (
    <Modal
      title={
        lockedScenario
          ? `Add files to ${lockedScenario.title}`
          : `Add documents to ${game.title}`
      }
      subtitle={
        lockedScenario
          ? `Maps, handouts and card decks attached to this scenario.${
              lockedScenario.campaign_title ? ` Campaign: ${lockedScenario.campaign_title}.` : ""
            }`
          : "The core rules are the primary source; supplements and campaigns are filed alongside."
      }
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
      footer={
        <>
          <span className="modal-foot-note">
            {doneCount > 0
              ? `${doneCount} uploaded`
              : busy
                ? "Uploading…"
                : `${queue.length} file(s) queued`}
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
      {lockedScenario ? (
        <div className="scenario-target">
          <Icon name="book" size={16} />
          <div>
            <strong>{lockedScenario.title}</strong>
            <span>
              {lockedScenario.campaign_title ?? "Ungrouped campaign"} · extra files are filed
              with this scenario
            </span>
          </div>
        </div>
      ) : (
        <>
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
                onChange={(event) => {
                  setCampaignId(event.target.value);
                  setScenarioId("");
                }}
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

          {role === "campaign" && scenarioOptions.length > 0 && (
            <label className="field">
              <span>
                Scenario <small>· optional</small>
              </span>
              <select
                value={scenarioId}
                onChange={(event) => setScenarioId(event.target.value)}
                disabled={busy}
              >
                <option value="">New scenario</option>
                {scenarioOptions.map((scenario) => (
                  <option key={scenario.id} value={scenario.id}>
                    {scenario.title}
                    {scenario.file_count ? ` (${scenario.file_count + 1} files)` : ""}
                  </option>
                ))}
              </select>
              <small className="fine-print">
                Pick a scenario to attach maps, handouts or cards to an existing scenario.
              </small>
            </label>
          )}
        </>
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
        <span className="fine-print">
          Images (maps, handouts) are stored and previewed but not text-indexed.
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

      {tooLarge.length > 0 && (
        <p className="form-error">
          Over the {maxUploadMb} MB limit: {tooLarge.join(", ")}. Raise
          RULESHELF_MAX_UPLOAD_MB and the reverse proxy's body-size limit to accept them.
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
              {item.status === "uploading" && (
                <>
                  {item.progress !== undefined && (
                    <small>{Math.round(item.progress * 100)}%</small>
                  )}
                  <span className="spinner" />
                </>
              )}
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

      {!lockedScenario && role === "campaign" && !scenarioId && pendingCount > 1 && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={groupFiles}
            onChange={(event) => setGroupFiles(event.target.checked)}
            disabled={busy}
          />
          File all {pendingCount} files under one new scenario
        </label>
      )}

      <p className="fine-print">
        Files up to {maxUploadMb} MB each; large books upload in pieces so proxy body limits do
        not block them. Scanned PDFs and images need a text layer (OCR) to be searchable; indexing
        happens in the background — you can keep using the app.
      </p>
    </Modal>
  );
}
