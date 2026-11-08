import { useState } from "react";
import { api, type Game, type GameType } from "../lib/api";
import { Modal } from "./Modal";

export function AddGameDialog({
  game,
  gameTypes,
  onClose,
  onSaved,
}: {
  game?: Game | null;
  gameTypes: GameType[];
  onClose: () => void;
  onSaved: (game: Game) => void;
}) {
  const [title, setTitle] = useState(game?.title ?? "");
  const [type, setType] = useState(game?.game_type ?? gameTypes[0]?.id ?? "rpg");
  const [description, setDescription] = useState(game?.description ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const selected = gameTypes.find((entry) => entry.id === type);

  const submit = async () => {
    if (!title.trim()) {
      setError("Give the game a title.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const saved = game
        ? await api.updateGame(game.id, {
            title: title.trim(),
            game_type: type,
            description: description.trim(),
          })
        : await api.createGame({
            title: title.trim(),
            game_type: type,
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
      title={game ? "Edit game" : "Add a game"}
      subtitle="A shelf for one game's rulebooks."
      onClose={onClose}
      footer={
        <>
          <button className="button ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="button primary" onClick={submit} disabled={saving}>
            {saving ? <span className="spinner light" /> : null}
            {game ? "Save changes" : "Create game"}
          </button>
        </>
      }
    >
      <label className="field">
        <span>Title</span>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="e.g. Warhammer Fantasy Roleplay 4e"
          autoFocus
        />
      </label>

      <div className="field">
        <span>Game type</span>
        <div className="type-options">
          {gameTypes.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={`type-option ${type === entry.id ? "selected" : ""}`}
              onClick={() => setType(entry.id)}
            >
              <span className={`type-dot type-${entry.id}`} />
              <strong>{entry.label}</strong>
              <small>{entry.description}</small>
            </button>
          ))}
        </div>
      </div>

      {selected && (
        <div className="role-preview">
          <span className="filter-label">Sections</span>
          {selected.roles.map((role) => (
            <span className="chip static" key={role.id}>
              {role.label}
            </span>
          ))}
        </div>
      )}

      <label className="field">
        <span>Description <small>(optional)</small></span>
        <textarea
          rows={3}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="A grim world of perilous adventure…"
        />
      </label>

      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
