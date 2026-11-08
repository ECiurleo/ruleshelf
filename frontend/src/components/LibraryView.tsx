import { plural, type Game, type GameType, type Stats } from "../lib/api";
import { Icon } from "./Icon";

export function LibraryView({
  games,
  gameTypes,
  stats,
  embeddingReady,
  canWrite = true,
  onOpenGame,
  onNewGame,
  onOpenSettings,
}: {
  games: Game[];
  gameTypes: GameType[];
  stats: Stats | null;
  embeddingReady: boolean;
  canWrite?: boolean;
  onOpenGame: (id: string) => void;
  onNewGame: () => void;
  onOpenSettings: () => void;
}) {
  return (
    <div className="view library-view">
      <section className="hero">
        <div>
          <p className="eyebrow">Tabletop rules assistant</p>
          <h1>
            Every rule,
            <br />
            <em>right where you need it.</em>
          </h1>
          <p className="hero-copy">
            Collect your core books, supplements and campaigns. Search them by keyword or
            meaning, and ask questions with answers cited back to the page.
          </p>
          <div className="hero-actions">
            {canWrite && (
              <button className="button primary" onClick={onNewGame}>
                <Icon name="plus" size={17} /> Add a game
              </button>
            )}
            {stats && (
              <span className="hero-stats">
                {plural(stats.games, "game")} · {plural(stats.documents, "book")} ·{" "}
                {stats.chunks.toLocaleString()} chunks indexed
              </span>
            )}
          </div>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="book-stack">
            <span className="book b1" />
            <span className="book b2" />
            <span className="book b3" />
            <span className="book b4" />
          </div>
          <span className="hero-die">
            <Icon name="dice" size={40} />
          </span>
        </div>
      </section>

      {!embeddingReady && (
        <div className="banner">
          <Icon name="sparkles" size={18} />
          <div>
            <strong>Semantic search is off.</strong> Keyword search works now. Add an embedding
            model — local Ollama is free — to search by meaning and get better AI answers.
          </div>
          {canWrite && (
            <button className="button ghost small" onClick={onOpenSettings}>
              Configure
            </button>
          )}
        </div>
      )}

      <div className="section-heading">
        <h2>Your shelf</h2>
        {canWrite && (
          <button className="button ghost small" onClick={onNewGame}>
            <Icon name="plus" size={15} /> New game
          </button>
        )}
      </div>

      {games.length === 0 ? (
        <div className="empty-panel">
          <span className="empty-mark">
            <Icon name="library" size={28} />
          </span>
          <h2>An empty shelf</h2>
          <p>
            Add a roleplaying game, board game or wargame, then upload its core rulebook. You can
            file supplements under expansions and adventures under campaigns.
          </p>
          {canWrite && (
            <button className="button primary" onClick={onNewGame}>
              <Icon name="plus" size={17} /> Add your first game
            </button>
          )}
        </div>
      ) : (
        <div className="game-grid">
          {games.map((game) => {
            const type = gameTypes.find((entry) => entry.id === game.game_type);
            const roles = type?.roles ?? [];
            return (
              <button className="game-card" key={game.id} onClick={() => onOpenGame(game.id)}>
                <div className="game-card-top">
                  <span className={`type-badge type-${game.game_type}`}>{game.type_label}</span>
                  <Icon name="chevron" size={17} />
                </div>
                <h3>{game.title}</h3>
                <p className="game-card-description">
                  {game.description || "No description yet."}
                </p>
                <div className="game-card-roles">
                  {roles.slice(0, 3).map((role) => (
                    <span key={role.id} className="role-pill">
                      <strong>{game.documents_by_role[role.id] ?? 0}</strong> {role.label}
                    </span>
                  ))}
                </div>
                <div className="game-card-footer">
                  <span>{game.chunk_count.toLocaleString()} chunks</span>
                  <span>{plural(game.document_count, "book")}</span>
                </div>
              </button>
            );
          })}
          {canWrite && (
            <button className="game-card add-card" onClick={onNewGame}>
              <Icon name="plus" size={26} />
              <span>Add another game</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
