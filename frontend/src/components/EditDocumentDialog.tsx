import { useState } from "react";
import { api, type Campaign, type Document, type GameType } from "../lib/api";
import { Modal } from "./Modal";

export function EditDocumentDialog({
  document,
  gameType,
  campaigns,
  onClose,
  onSaved,
  notify,
}: {
  document: Document;
  gameType: GameType | undefined;
  campaigns: Campaign[];
  onClose: () => void;
  onSaved: () => Promise<void> | void;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const roles = gameType?.roles ?? [{ id: "core", label: "Core rules" }];
  const options = roles.some((entry) => entry.id === document.role)
    ? roles
    : [
        ...roles,
        {
          id: document.role,
          label: document.role.replace(/_/g, " "),
        },
      ];
  const [title, setTitle] = useState(document.title);
  const [role, setRole] = useState(document.role);
  const [campaignId, setCampaignId] = useState(document.campaign_id ?? "");
  const [order, setOrder] = useState(String(document.sort_order ?? 0));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    const nextTitle = title.trim();
    if (!nextTitle) {
      setError("Title is required.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.updateDocument(document.id, {
        title: nextTitle,
        role,
        campaign_id: role === "campaign" ? campaignId || null : null,
        sort_order:
          role === "campaign" ? Math.max(0, Number(order) || 0) : 0,
      });
      notify("Document updated.", "ok");
      await onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Edit document"
      subtitle={document.original_filename}
      onClose={onClose}
      footer={
        <>
          <button className="button ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="button primary" onClick={save} disabled={busy}>
            {busy ? <span className="spinner light" /> : null}
            Save changes
          </button>
        </>
      }
    >
      <label className="field">
        <span>Title</span>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          autoFocus
        />
      </label>
      <label className="field">
        <span>Section</span>
        <select value={role} onChange={(event) => setRole(event.target.value)}>
          {options.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.label}
            </option>
          ))}
        </select>
      </label>
      {role === "campaign" && (
        <>
          <label className="field">
            <span>Campaign <small>· optional</small></span>
            <select
              value={campaignId}
              onChange={(event) => setCampaignId(event.target.value)}
            >
              <option value="">Ungrouped campaign document</option>
              {campaigns.map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  {campaign.title}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Scenario order</span>
            <input
              type="number"
              min={0}
              value={order}
              onChange={(event) => setOrder(event.target.value)}
            />
          </label>
        </>
      )}
      <p className="fine-print">
        Moving a document to another section changes its search role immediately. No
        re-indexing is needed. Moving out of Campaigns clears its campaign assignment.
      </p>
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
