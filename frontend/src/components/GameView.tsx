import { plural, type Document, type Game, type GameType } from "../lib/api";
import { Icon } from "./Icon";
import { DocumentCard } from "./DocumentCard";

export function GameView({
  game,
  gameType,
  documents,
  embeddingConfigured,
  onUpload,
  onEdit,
  onDelete,
  onOpenDoc,
  onReindexDoc,
  onDeleteDoc,
  onRetitleDoc,
}: {
  game: Game;
  gameType: GameType | undefined;
  documents: Document[];
  embeddingConfigured: boolean;
  onUpload: (role: string) => void;
  onEdit: () => void;
  onDelete: () => void;
  onOpenDoc: (doc: Document) => void;
  onReindexDoc: (doc: Document) => void;
  onDeleteDoc: (doc: Document) => void;
  onRetitleDoc: (doc: Document, title: string) => void;
}) {
  const roles = gameType?.roles ?? [{ id: "core", label: "Core rules" }];
  const known = new Set(roles.map((role) => role.id));
  const extraRoles = [...new Set(documents.map((doc) => doc.role))].filter(
    (role) => !known.has(role),
  );
  const sections = [
    ...roles,
    ...extraRoles.map((role) => ({ id: role, label: role.replace(/_/g, " ") })),
  ];
  const processing = documents.filter(
    (doc) => doc.status === "pending" || doc.status === "processing",
  ).length;

  return (
    <div className="view game-view">
      <header className="game-header">
        <div className="game-heading">
          <span className={`type-badge type-${game.game_type}`}>{game.type_label}</span>
          <h1>{game.title}</h1>
          {game.description && <p className="game-description">{game.description}</p>}
          <div className="game-meta">
            <span>{plural(documents.length, "document")}</span>
            <span className="dot-sep" />
            <span>{game.chunk_count.toLocaleString()} indexed chunks</span>
            {processing > 0 && (
              <>
                <span className="dot-sep" />
                <span className="text-warn">
                  <span className="spinner" /> {processing} indexing
                </span>
              </>
            )}
          </div>
        </div>
        <div className="game-actions">
          <button className="button primary" onClick={() => onUpload("core")}>
            <Icon name="upload" size={17} /> Add document
          </button>
          <button className="icon-button" onClick={onEdit} title="Edit game" aria-label="Edit game">
            <Icon name="edit" size={17} />
          </button>
          <button
            className="icon-button danger"
            onClick={onDelete}
            title="Delete game"
            aria-label="Delete game"
          >
            <Icon name="trash" size={17} />
          </button>
        </div>
      </header>

      {documents.length === 0 ? (
        <div className="empty-panel">
          <span className="empty-mark">
            <Icon name="book" size={28} />
          </span>
          <h2>No rulebooks yet</h2>
          <p>
            Add the core {game.game_type === "rpg" ? "rulebook" : "rules"} first — that becomes
            the primary source. Supplements and campaigns go alongside it.
          </p>
          <button className="button primary" onClick={() => onUpload("core")}>
            <Icon name="upload" size={17} /> Upload the core rules
          </button>
          <p className="fine-print">PDF, EPUB, DOCX, Markdown or plain text.</p>
        </div>
      ) : (
        <div className="role-sections">
          {sections.map((role) => {
            const docs = documents.filter((doc) => doc.role === role.id);
            if (!docs.length && role.id !== "core") return null;
            return (
              <section className="role-section" key={role.id}>
                <div className="role-heading">
                  <h2>
                    {role.label}
                    {role.id === "core" && <span className="primary-tag">primary source</span>}
                  </h2>
                  <div className="role-heading-right">
                    <span className="role-count">{plural(docs.length, "book")}</span>
                    <button className="button ghost small" onClick={() => onUpload(role.id)}>
                      <Icon name="plus" size={15} /> Add
                    </button>
                  </div>
                </div>
                {docs.length ? (
                  <div className="document-list">
                    {docs.map((doc) => (
                      <DocumentCard
                        key={doc.id}
                        document={doc}
                        embeddingConfigured={embeddingConfigured}
                        onOpen={() => onOpenDoc(doc)}
                        onReindex={() => onReindexDoc(doc)}
                        onDelete={() => onDeleteDoc(doc)}
                        onRetitle={(title) => onRetitleDoc(doc, title)}
                      />
                    ))}
                  </div>
                ) : (
                  <button className="dropzone small" onClick={() => onUpload(role.id)}>
                    <Icon name="plus" size={18} />
                    Add a {role.label.toLowerCase()} document
                  </button>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
