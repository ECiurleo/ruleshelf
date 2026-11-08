import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ask,
  type AppSettings,
  type Document,
  type Game,
  type GameType,
  type ProviderList,
  type SearchResult,
  type Stats,
} from "./lib/api";
import { Sidebar } from "./components/Sidebar";
import { SearchBar, type SearchMode } from "./components/SearchBar";
import { LibraryView } from "./components/LibraryView";
import { GameView } from "./components/GameView";
import { ResultsView } from "./components/ResultsView";
import { ReaderDrawer, type ReaderTarget } from "./components/ReaderDrawer";
import { AddGameDialog } from "./components/AddGameDialog";
import { UploadDialog } from "./components/UploadDialog";
import { SettingsDialog } from "./components/SettingsDialog";
import { Icon } from "./components/Icon";

interface Toast {
  id: number;
  message: string;
  kind: "ok" | "error";
}

interface SearchMeta {
  mode_used: string;
  note: string | null;
  provider?: string;
  model?: string;
  embedding?: { provider_name: string; model: string } | null;
}

export default function App() {
  const [games, setGames] = useState<Game[]>([]);
  const [gameTypes, setGameTypes] = useState<GameType[]>([]);
  const [bundle, setBundle] = useState<AppSettings | null>(null);
  const [providers, setProviders] = useState<ProviderList | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);

  const [activeGameId, setActiveGameId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [answerMode, setAnswerMode] = useState(false);
  const [searchAllGames, setSearchAllGames] = useState(false);
  const [roles, setRoles] = useState<string[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [meta, setMeta] = useState<SearchMeta | null>(null);
  const [answer, setAnswer] = useState("");
  const [searchError, setSearchError] = useState("");

  const [chatChoice, setChatChoice] = useState<{ providerId: string; model: string } | null>(
    () => {
      try {
        return JSON.parse(localStorage.getItem("ruleshelf:answerModel") ?? "null");
      } catch {
        return null;
      }
    },
  );

  const [reader, setReader] = useState<ReaderTarget | null>(null);
  const [addGameOpen, setAddGameOpen] = useState(false);
  const [editingGame, setEditingGame] = useState<Game | null>(null);
  const [uploadRole, setUploadRole] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [toast, setToast] = useState<Toast | null>(null);
  const toastTimer = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const answerInitialized = useRef(false);
  const answerRef = useRef("");
  const conversationRef = useRef<{ role: "user" | "assistant"; content: string }[]>([]);

  const notify = useCallback((message: string, kind: "ok" | "error" = "ok") => {
    setToast({ id: Date.now(), message, kind });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4500);
  }, []);

  const refreshLibrary = useCallback(async () => {
    const [gameList, typeList, settings, providerList, statsResult] = await Promise.all([
      api.games(),
      api.gameTypes(),
      api.settings(),
      api.providers(),
      api.stats(),
    ]);
    setGames(gameList.games);
    setGameTypes(typeList.game_types);
    setBundle(settings);
    setProviders(providerList);
    setStats(statsResult);
  }, []);

  const refreshDocuments = useCallback(async (gameId: string | null) => {
    if (!gameId) {
      setDocuments([]);
      return;
    }
    const result = await api.documents(gameId);
    setDocuments(result.documents);
  }, []);

  // Initial load
  useEffect(() => {
    refreshLibrary()
      .catch((err: Error) => setLoadError(err.message))
      .finally(() => setLoading(false));
  }, [refreshLibrary]);

  // Answers are the default when a chat provider is configured; the toggle
  // still allows results-only searches.
  useEffect(() => {
    if (!bundle || answerInitialized.current) return;
    setAnswerMode(bundle.info.chat_ready);
    answerInitialized.current = true;
  }, [bundle]);

  // Hash routing: #/game/<id> or #/
  useEffect(() => {
    const applyHash = () => {
      const match = window.location.hash.match(/^#\/game\/([^/?#]+)/);
      setActiveGameId(match ? decodeURIComponent(match[1]) : null);
    };
    applyHash();
    window.addEventListener("hashchange", applyHash);
    return () => window.removeEventListener("hashchange", applyHash);
  }, []);

  // Documents for the selected game
  useEffect(() => {
    let cancelled = false;
    setDocsLoading(Boolean(activeGameId));
    refreshDocuments(activeGameId)
      .catch((err: Error) => notify(err.message, "error"))
      .finally(() => {
        if (!cancelled) setDocsLoading(false);
      });
    setHasSearched(false);
    setResults([]);
    setMeta(null);
    setAnswer("");
    setSearchError("");
    setRoles([]);
    conversationRef.current = [];
    return () => {
      cancelled = true;
    };
  }, [activeGameId, refreshDocuments, notify]);

  // Drop a remembered model if its provider was removed or disabled.
  useEffect(() => {
    if (!chatChoice || !providers) return;
    const provider = providers.providers.find((entry) => entry.id === chatChoice.providerId);
    if (!provider || !provider.enabled) {
      setChatChoice(null);
      localStorage.removeItem("ruleshelf:answerModel");
    }
  }, [providers, chatChoice]);

  // Poll while any document is being indexed
  const hasProcessing = documents.some(
    (doc) => doc.status === "pending" || doc.status === "processing",
  );
  useEffect(() => {
    if (!activeGameId || !hasProcessing) return;
    const timer = window.setTimeout(async () => {
      try {
        await refreshDocuments(activeGameId);
        const gameList = await api.games();
        setGames(gameList.games);
        setStats(await api.stats());
      } catch {
        /* transient; try again next tick */
      }
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [activeGameId, hasProcessing, documents, refreshDocuments]);

  const activeGame = games.find((game) => game.id === activeGameId) ?? null;
  const activeGameType = gameTypes.find((type) => type.id === activeGame?.game_type);

  // If a deep link points at a missing game, fall back to the library.
  useEffect(() => {
    if (loading || !activeGameId || games.length === 0) return;
    if (!games.some((game) => game.id === activeGameId)) {
      window.location.hash = "#/";
    }
  }, [games, activeGameId, loading]);

  const navigate = (gameId: string | null) => {
    window.location.hash = gameId ? `#/game/${gameId}` : "#/";
    setSidebarOpen(false);
    setHasSearched(false);
    setQuery("");
    setResults([]);
    setMeta(null);
    setAnswer("");
    setSearchError("");
  };

  const stopAsking = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setSearching(false);
  };

  const runSearch = async () => {
    const text = query.trim();
    if (!text) return;
    stopAsking();
    setSearching(true);
    setHasSearched(true);
    setResults([]);
    setMeta(null);
    setAnswer("");
    setSearchError("");
    answerRef.current = "";
    const scope = activeGameId && !searchAllGames ? activeGameId : undefined;

    if (!answerMode) {
      try {
        const response = await api.search({
          q: text,
          mode,
          game_id: scope,
          roles,
          limit: 30,
        });
        setResults(response.results);
        setMeta({
          mode_used: response.mode_used,
          note: response.note,
          embedding: response.embedding,
        });
      } catch (err) {
        setSearchError((err as Error).message);
      } finally {
        setSearching(false);
      }
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    const history = conversationRef.current.slice(-6);
    try {
      await ask(
        {
          query: text,
          game_id: scope,
          roles,
          mode,
          history,
          provider_id: chatChoice?.providerId,
          model: chatChoice?.model || undefined,
        },
        {
          onSources: (payload) => {
            setResults(payload.sources);
            setMeta({
              mode_used: payload.mode_used,
              note: payload.note,
              provider: payload.provider,
              model: payload.model,
              embedding: payload.embedding,
            });
          },
          onToken: (token) => {
            answerRef.current += token;
            setAnswer(answerRef.current);
          },
          onError: (message) => setSearchError(message),
          onDone: () => setSearching(false),
        },
        controller.signal,
      );
      // Keep the follow-up context free of the appended references block.
      const previousAnswer = answerRef.current
        .replace(/\n---\n\n#### References[\s\S]*$/, "")
        .trim();
      if (previousAnswer) {
        const exchange: { role: "user" | "assistant"; content: string }[] = [
          { role: "user", content: text },
          { role: "assistant", content: previousAnswer },
        ];
        conversationRef.current = [...conversationRef.current, ...exchange].slice(-8);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setSearchError((err as Error).message);
        // If no provider is configured (or it fails before streaming), still
        // show useful search results.
        try {
          const fallback = await api.search({
            q: text,
            mode,
            game_id: scope,
            roles,
            limit: 30,
          });
          setResults(fallback.results);
          setMeta({
            mode_used: fallback.mode_used,
            note: fallback.note,
            embedding: fallback.embedding,
          });
        } catch {
          /* keep the original error */
        }
      }
    } finally {
      setSearching(false);
      abortRef.current = null;
    }
  };

  const openReaderForDocument = (doc: Document) => {
    const game = games.find((entry) => entry.id === doc.game_id);
    const type = gameTypes.find((entry) => entry.id === game?.game_type);
    setReader({
      documentId: doc.id,
      title: doc.title,
      page: 1,
      gameTitle: game?.title,
      roleLabel: type?.roles.find((role) => role.id === doc.role)?.label,
    });
  };

  const openReaderForResult = (result: SearchResult) => {
    setReader({
      documentId: result.document.id,
      title: result.document.title,
      page: result.page_start ?? 1,
      gameTitle: result.game.title,
      roleLabel: result.document.role_label,
    });
  };

  const deleteGame = async () => {
    if (!activeGame) return;
    if (
      !window.confirm(
        `Delete "${activeGame.title}" and all of its documents? This cannot be undone.`,
      )
    ) {
      return;
    }
    try {
      await api.deleteGame(activeGame.id);
      await refreshLibrary();
      navigate(null);
      notify("Game deleted.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const deleteDocument = async (doc: Document) => {
    if (!window.confirm(`Delete "${doc.title}"? This removes its index and file.`)) return;
    try {
      await api.deleteDocument(doc.id);
      await refreshDocuments(activeGameId);
      await refreshLibrary();
      notify("Document deleted.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const reindexDocument = async (doc: Document) => {
    try {
      await api.reindexDocument(doc.id);
      await refreshDocuments(activeGameId);
      notify("Re-indexing started.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const retitleDocument = async (doc: Document, title: string) => {
    try {
      await api.updateDocument(doc.id, { title });
      await refreshDocuments(activeGameId);
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const searchBusy = searching;

  const mainContent = () => {
    if (loading) {
      return (
        <div className="view loading-view">
          <span className="spinner large" />
          <p>Opening the shelf…</p>
        </div>
      );
    }
    if (loadError) {
      return (
        <div className="empty-panel">
          <span className="empty-mark">
            <Icon name="alert" size={26} />
          </span>
          <h2>Cannot reach the server</h2>
          <p>{loadError}</p>
          <button className="button primary" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      );
    }
    if (hasSearched) {
      return (
        <ResultsView
          query={query}
          results={results}
          meta={meta}
          answerMode={answerMode}
          asking={searching}
          answer={answer}
          error={searchError}
          onOpenResult={openReaderForResult}
          onStop={stopAsking}
          onConfigure={() => setSettingsOpen(true)}
        />
      );
    }
    if (activeGame) {
      return (
        <GameView
          game={activeGame}
          gameType={activeGameType}
          documents={documents}
          embeddingConfigured={bundle?.info.embedding_ready ?? false}
          onUpload={(role) => setUploadRole(role)}
          onEdit={() => setEditingGame(activeGame)}
          onDelete={deleteGame}
          onOpenDoc={openReaderForDocument}
          onReindexDoc={reindexDocument}
          onDeleteDoc={deleteDocument}
          onRetitleDoc={retitleDocument}
        />
      );
    }
    if (docsLoading && activeGameId) {
      return (
        <div className="view loading-view">
          <span className="spinner large" />
        </div>
      );
    }
    return (
      <LibraryView
        games={games}
        gameTypes={gameTypes}
        stats={stats}
        embeddingReady={bundle?.info.embedding_ready ?? false}
        onOpenGame={(id) => navigate(id)}
        onNewGame={() => setAddGameOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
      />
    );
  };

  return (
    <div className="app-shell">
      <Sidebar
        games={games}
        activeGameId={activeGameId}
        stats={stats}
        version={bundle?.info.version ?? "0.1.0"}
        open={sidebarOpen}
        onSelect={navigate}
        onNewGame={() => {
          setSidebarOpen(false);
          setAddGameOpen(true);
        }}
        onSettings={() => {
          setSidebarOpen(false);
          setSettingsOpen(true);
        }}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="app-main">
        <header className="topbar">
          <button
            className="icon-button menu-toggle"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open menu"
          >
            <Icon name="library" size={19} />
          </button>
          <SearchBar
            query={query}
            setQuery={setQuery}
            mode={mode}
            setMode={setMode}
            answerMode={answerMode}
            setAnswerMode={setAnswerMode}
            onSubmit={runSearch}
            onClear={() => {
              setQuery("");
              setHasSearched(false);
              setResults([]);
              setMeta(null);
              setAnswer("");
              setSearchError("");
              conversationRef.current = [];
            }}
            busy={searchBusy}
            activeGame={activeGame}
            gameType={activeGameType}
            searchAllGames={searchAllGames}
            setSearchAllGames={setSearchAllGames}
            roles={roles}
            setRoles={setRoles}
            providers={providers?.providers ?? []}
            chatChoice={chatChoice}
            setChatChoice={(choice) => {
              setChatChoice(choice);
              localStorage.setItem("ruleshelf:answerModel", JSON.stringify(choice));
            }}
            defaultChatProvider={
              bundle?.info.provider_names[bundle?.settings.default_chat_provider ?? ""] ?? ""
            }
            defaultChatModel={bundle?.settings.default_chat_model ?? ""}
          />
          <button
            className="icon-button topbar-settings"
            onClick={() => setSettingsOpen(true)}
            aria-label="Settings"
            title="Settings"
          >
            <Icon name="settings" size={19} />
          </button>
        </header>

        <main className="main">{mainContent()}</main>
      </div>

      <ReaderDrawer target={reader} onClose={() => setReader(null)} />

      {addGameOpen && (
        <AddGameDialog
          gameTypes={gameTypes}
          onClose={() => setAddGameOpen(false)}
          onSaved={async (game) => {
            await refreshLibrary();
            navigate(game.id);
            notify(`"${game.title}" added. Upload its core rules to begin.`, "ok");
          }}
        />
      )}

      {editingGame && (
        <AddGameDialog
          game={editingGame}
          gameTypes={gameTypes}
          onClose={() => setEditingGame(null)}
          onSaved={async () => {
            await refreshLibrary();
            notify("Game updated.", "ok");
          }}
        />
      )}

      {uploadRole && activeGame && (
        <UploadDialog
          game={activeGame}
          gameType={activeGameType}
          formats={bundle?.info.formats ?? []}
          initialRole={uploadRole}
          onClose={() => setUploadRole(null)}
          onUploaded={async () => {
            await refreshDocuments(activeGame.id);
            const gameList = await api.games();
            setGames(gameList.games);
          }}
          notify={notify}
        />
      )}

      {settingsOpen && bundle && providers && (
        <SettingsDialog
          bundle={bundle}
          providers={providers}
          onClose={() => setSettingsOpen(false)}
          onRefresh={refreshLibrary}
          notify={notify}
        />
      )}

      {toast && (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} size={16} />
          <span>{toast.message}</span>
          <button className="icon-button small" onClick={() => setToast(null)} aria-label="Dismiss">
            <Icon name="close" size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
