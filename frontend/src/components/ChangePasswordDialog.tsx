import { useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./Modal";

export function ChangePasswordDialog({
  onClose,
  notify,
}: {
  onClose: () => void;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (next.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }
    if (next !== confirm) {
      setError("New passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.changePassword(current, next);
      notify("Password changed. Other sessions were signed out.", "ok");
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Change password"
      subtitle="Other sessions for this account will be signed out."
      onClose={onClose}
      footer={
        <>
          <button className="button ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="button primary" onClick={save} disabled={busy}>
            {busy ? <span className="spinner light" /> : null}
            Change password
          </button>
        </>
      }
    >
      <label className="field">
        <span>Current password</span>
        <input
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          autoFocus
        />
      </label>
      <label className="field">
        <span>New password</span>
        <input
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
      </label>
      <label className="field">
        <span>Confirm new password</span>
        <input
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
      </label>
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
