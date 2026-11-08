import type { Game, GameType, Provider } from "../lib/api";
import { Icon } from "./Icon";
import { ModelPicker, type ModelChoice } from "./ModelPicker";

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
  answerMode,
  setAnswerMode,
  onSubmit,
  onClear,
  busy,
  activeGame,
  gameType,
  searchAllGames,
  setSearchAllGames,
  roles,
  setRoles,
  providers,
  chatChoice,
  setChatChoice,
  defaultChatProvider,
  defaultChatModel,
  includeBgg,
  setIncludeBgg,
}: {
  query: string;
  setQuery: (value: string) => void;
  mode: SearchMode;
  setMode: (value: SearchMode) => void;
  answerMode: boolean;
  setAnswerMode: (value: boolean) => void;
  onSubmit: () => void;
  onClear: () => void;
  busy: boolean;
  activeGame: Game | null;
  gameType: GameType | undefined;
  searchAllGames: boolean;
  setSearchAllGames: (value: boolean) => void;
  roles: string[];
  setRoles: (value: string[]) => void;
  providers: Provider[];
  chatChoice: ModelChoice | null;
  setChatChoice: (value: ModelChoice | null) => void;
  defaultChatProvider: string;
  defaultChatModel: string;
  includeBgg: boolean;
  setIncludeBgg: (value: boolean) => void;
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
          <Icon name={answerMode ? "sparkles" : "search"} size={20} />
        </span>
        <input
          className="search-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={
            answerMode
              ? "Ask a rules question… e.g. “how fast can a dwarf run?”"
              : "Search rules… e.g. “charge reaction”, “critical injury table”"
          }
          autoComplete="off"
          spellCheck={false}
          aria-label={answerMode ? "Ask a question" : "Search rules"}
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

        <label
          className={`ask-toggle ${answerMode ? "on" : ""}`}
          title="Answer from your rulebooks at the top of the results"
        >
          <input
            type="checkbox"
            checked={answerMode}
            onChange={(event) => setAnswerMode(event.target.checked)}
          />
          <Icon name="sparkles" size={16} />
          <span>Answer</span>
        </label>

        <button className="button primary search-submit" type="submit" disabled={busy || !query.trim()}>
          {busy ? <span className="spinner light" /> : answerMode ? "Ask" : "Search"}
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
        {answerMode && (
          <ModelPicker
            providers={providers}
            value={chatChoice}
            defaultProvider={defaultChatProvider}
            defaultModel={defaultChatModel}
            onChange={setChatChoice}
          />
        )}
        {answerMode && (
          <label
            className={`bgg-toggle ${includeBgg ? "on" : ""}`}
            title="Also search BoardGameGeek forum threads via web search. Unofficial; rulebooks are prioritised."
          >
            <input
              type="checkbox"
              checked={includeBgg}
              onChange={(event) => setIncludeBgg(event.target.checked)}
            />
            <Icon name="external" size={13} />
            <span>BGG forums</span>
          </label>
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
