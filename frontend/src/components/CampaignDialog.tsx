import { useState } from "react";
import { api, type Campaign } from "../lib/api";
import { Modal } from "./Modal";

export function CampaignDialog({
  gameId,
  campaign,
  onClose,
  onSaved,
}: {
  gameId: string;
  campaign?: Campaign | null;
  onClose: () => void;
  onSaved: (campaign: Campaign) => void;
}) {
  const [title, setTitle] = useState(campaign?.title ?? "");
  const [description, setDescription] = useState(campaign?.description ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (!title.trim()) {
      setError("Give the campaign a title.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const saved = campaign
        ? await api.updateCampaign(campaign.id, {
            title: title.trim(),
            description: description.trim(),
          })
        : await api.createCampaign(gameId, {
            title: title.trim(),
            description: description.trim(),
          });
      onSaved(saved);
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={campaign ? "Edit campaign" : "New campaign"}
      subtitle="Group the scenarios or books that belong to one campaign."
      onClose={onClose}
      footer={
        <>
          <button className="button ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="button primary" onClick={save} disabled={saving}>
            {saving ? <span className="spinner light" /> : null}
            {campaign ? "Save changes" : "Create campaign"}
          </button>
        </>
      }
    >
      <label className="field">
        <span>Campaign title</span>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="e.g. The Enemy Within"
          autoFocus
        />
      </label>
      <label className="field">
        <span>
          Description <small>(optional)</small>
        </span>
        <textarea
          rows={3}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="A five-part campaign for WFRP…"
        />
      </label>
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
