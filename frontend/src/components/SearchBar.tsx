import type { Game, GameType } from "../lib/api";
import { Icon } from "./Icon";

export type SearchMode = "keyword" | "hybrid" | "semantic";

const MODES: { id: SearchMode; label: string; hint: string }[] = [
  { id: "keyword", label: "Keyword", hint: "Exact words, names and tables" },
  { id: "hybrid", label: "Smart", hint: "Keyword + meaning, best of both" },
  { id: "semantic", label: "Meaning", hint: "Conceptual search via embeddings" },
];

export function SearchBar({
  query,
  setQuery,
  mode,
  setMode,
  askMode,
  setAskMode,
  onSubmit,
  onClear,
  busy,
  activeGame,
  gameType,
  searchAllGames,
  setSearchAllGames,
  roles,
  setRoles,
}: {
  query: string;
  setQuery: (value: string) => void;
  mode: SearchMode;
  setMode: (value: SearchMode) => void;
  askMode: boolean;
  setAskMode: (value: boolean) => void;
  onSubmit: () => void;
  onClear: () => void;
  busy: boolean;
  activeGame: Game | null;
  gameType: GameType | undefined;
  searchAllGames: boolean;
  setSearchAllGames: (value: boolean) => void;
  roles: string[];
  setRoles: (value: string[]) => void;
}) {
  const roleOptions = activeGame && !searchAllGames
    ? gameType?.roles ?? []
    : [
        { id: "core", label: "Core rules" },
        { id: "expansion", label: "Supplements" },
        { id: "campaign", label: "Campaigns" },
        { id: "other", label: "Other" },
      ];

  const toggleRole = (role: string) => {
    setRoles(roles.includes(role) ? roles.filter((item) => item !== role) : [...roles, role]);
  };

  return (
    <div className="search-shell">
      <form
        className="search-form"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <span className="search-icon">
          <Icon name={askMode ? "sparkles" : "search"} size={20} />
        </span>
        <input
          className="search-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={
            askMode
              ? "Ask a rules question… e.g. “how does a miscast work?”"
              : "Search rules… e.g. “charge reaction”, “critical injury table”"
          }
          autoComplete="off"
          spellCheck={false}
          aria-label={askMode ? "Ask a question" : "Search rules"}
        />
        {query && (
          <button
            type="button"
            className="icon-button search-clear"
            onClick={onClear}
            title="Clear"
            aria-label="Clear search"
          >
            <Icon name="close" size={17} />
          </button>
        )}

        <div className="mode-switch" role="group" aria-label="Search mode">
          {MODES.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={mode === entry.id ? "selected" : ""}
              onClick={() => setMode(entry.id)}
              title={entry.hint}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <label className={`ask-toggle ${askMode ? "on" : ""}`} title="Answer with an AI provider">
          <input
            type="checkbox"
            checked={askMode}
            onChange={(event) => setAskMode(event.target.checked)}
          />
          <Icon name="sparkles" size={16} />
          <span>Ask AI</span>
        </label>

        <button className="button primary search-submit" type="submit" disabled={busy || !query.trim()}>
          {busy ? <span className="spinner light" /> : askMode ? "Ask" : "Search"}
        </button>
      </form>

      <div className="search-filters">
        {activeGame && (
          <button
            type="button"
            className={`scope-toggle ${searchAllGames ? "" : "selected"}`}
            onClick={() => setSearchAllGames(!searchAllGames)}
            title="Toggle between this game and the whole library"
          >
            <Icon name="book" size={14} />
            {searchAllGames ? "All games" : `In ${activeGame.title}`}
          </button>
        )}
        <span className="filter-label">Roles</span>
        {roleOptions.map((role) => (
          <button
            type="button"
            key={role.id}
            className={`chip ${roles.includes(role.id) ? "selected" : ""}`}
            onClick={() => toggleRole(role.id)}
          >
            {role.label}
          </button>
        ))}
        {roles.length > 0 && (
          <button type="button" className="link-button" onClick={() => setRoles([])}>
            clear
          </button>
        )}
        <span className="filter-note">
          {mode === "semantic"
            ? "Uses your embedding model"
            : mode === "hybrid"
              ? "Keyword first, meaning second"
              : "Exact word matching"}
        </span>
      </div>
    </div>
  );
}
