import { plural, type Game, type Stats } from "../lib/api";
import { Icon } from "./Icon";

export function Sidebar({
  games,
  activeGameId,
  stats,
  version,
  open,
  canWrite = true,
  onSelect,
  onNewGame,
  onSettings,
  theme,
  onToggleTheme,
  onClose,
}: {
  games: Game[];
  activeGameId: string | null;
  stats: Stats | null;
  version: string;
  open: boolean;
  canWrite?: boolean;
  onSelect: (id: string | null) => void;
  onNewGame: () => void;
  onSettings: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onClose: () => void;
}) {
  return (
    <>
      <div className={`sidebar-scrim ${open ? "open" : ""}`} onClick={onClose} aria-hidden="true" />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">
            <Icon name="book" size={20} />
          </span>
          <span className="brand-text">
            <strong>Ruleshelf</strong>
            <small>your rulebooks, searchable</small>
          </span>
          <button className="icon-button sidebar-close" onClick={onClose} aria-label="Close menu">
            <Icon name="close" size={18} />
          </button>
        </div>

        <nav className="sidebar-nav">
          <button
            className={`nav-item ${activeGameId === null ? "active" : ""}`}
            onClick={() => onSelect(null)}
          >
            <Icon name="library" size={17} />
            <span>Library</span>
            <span className="nav-count">{games.length}</span>
          </button>

          <div className="nav-heading">
            <span>Games</span>
            {canWrite && (
              <button
                className="icon-button small"
                onClick={onNewGame}
                title="Add a game"
                aria-label="Add a game"
              >
                <Icon name="plus" size={15} />
              </button>
            )}
          </div>

          <div className="game-list">
            {games.map((game) => (
              <button
                key={game.id}
                className={`nav-item game ${activeGameId === game.id ? "active" : ""}`}
                onClick={() => onSelect(game.id)}
                title={`${game.type_label} · ${game.document_count} document(s)`}
              >
                <span className={`type-dot type-${game.game_type}`} />
                <span className="game-name">{game.title}</span>
                <span className="nav-count">{game.document_count || ""}</span>
              </button>
            ))}
            {games.length === 0 && (
              <p className="sidebar-empty">
                No games yet.
                {canWrite && (
                  <button className="link-button" onClick={onNewGame}>
                    Add your first one
                  </button>
                )}
              </p>
            )}
          </div>
        </nav>

        <div className="sidebar-footer">
          {stats && (
            <div className="library-stats">
              <span>{plural(stats.documents, "book")}</span>
              <span className="dot-sep" />
              <span>{stats.chunks.toLocaleString()} chunks</span>
              {stats.documents_by_status.error ? (
                <>
                  <span className="dot-sep" />
                  <span className="text-danger">{stats.documents_by_status.error} failed</span>
                </>
              ) : null}
            </div>
          )}
          <button className="nav-item" onClick={onToggleTheme}>
            <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
            <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
          </button>
          {canWrite && (
            <button className="nav-item" onClick={onSettings}>
              <Icon name="settings" size={17} />
              <span>Settings</span>
            </button>
          )}
          <div className="version">v{version}</div>
        </div>
      </aside>
    </>
  );
}
