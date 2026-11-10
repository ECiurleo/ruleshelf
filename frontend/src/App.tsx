import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ask,
  type AppSettings,
  type Campaign,
  type Document,
  type Game,
  type GameType,
  type ProviderList,
  type SearchResult,
  type Stats,
  type User,
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
import { CampaignDialog } from "./components/CampaignDialog";
import { EditDocumentDialog } from "./components/EditDocumentDialog";
import { LoginPage } from "./components/LoginPage";
import { ChangePasswordDialog } from "./components/ChangePasswordDialog";
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
  bgg_count?: number;
  reddit_count?: number;
  bgg_note?: string | null;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);

  const [games, setGames] = useState<Game[]>([]);
  const [gameTypes, setGameTypes] = useState<GameType[]>([]);
  const [bundle, setBundle] = useState<AppSettings | null>(null);
  const [providers, setProviders] = useState<ProviderList | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );

  const [activeGameId, setActiveGameId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [answerMode, setAnswerMode] = useState(false);
  const [includeBgg, setIncludeBggState] = useState(
    // On by default; an explicit "0" remembers an opt-out.
    () => localStorage.getItem("ruleshelf:includeBgg") !== "0",
  );
  const [searchAllGames, setSearchAllGames] = useState(false);
  const [roles, setRoles] = useState<string[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [meta, setMeta] = useState<SearchMeta | null>(null);
  const [answer, setAnswer] = useState("");
  const [communityAnswer, setCommunityAnswer] = useState("");
  const [communityStreaming, setCommunityStreaming] = useState(false);
  const [communityError, setCommunityError] = useState("");
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
  const [editingDoc, setEditingDoc] = useState<Document | null>(null);
  const [uploadRole, setUploadRole] = useState<string | null>(null);
  const [uploadCampaignId, setUploadCampaignId] = useState<string | null>(null);
  const [uploadScenarioId, setUploadScenarioId] = useState<string | null>(null);
  const [campaignDialog, setCampaignDialog] = useState<{ campaign?: Campaign } | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [toast, setToast] = useState<Toast | null>(null);
  const toastTimer = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const answerInitialized = useRef(false);
  const answerRef = useRef("");
  const communityRef = useRef("");
  const conversationRef = useRef<{ role: "user" | "assistant"; content: string }[]>([]);

  const notify = useCallback((message: string, kind: "ok" | "error" = "ok") => {
    setToast({ id: Date.now(), message, kind });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4500);
  }, []);

  const refreshLibrary = useCallback(async () => {
    const [gameList, typeList, settings, statsResult] = await Promise.all([
      api.games(),
      api.gameTypes(),
      api.settings(),
      api.stats(),
    ]);
    setGames(gameList.games);
    setGameTypes(typeList.game_types);
    setBundle(settings);
    setStats(statsResult);
    // Provider settings are administrator-only; viewers get library data.
    if (user?.role === "admin") {
      setProviders(await api.providers());
    } else {
      setProviders(null);
    }
  }, [user?.role]);

  const refreshDocuments = useCallback(async (gameId: string | null) => {
    if (!gameId) {
      setDocuments([]);
      return;
    }
    const result = await api.documents(gameId);
    setDocuments(result.documents);
  }, []);

  const refreshCampaigns = useCallback(async (gameId: string | null) => {
    if (!gameId) {
      setCampaigns([]);
      return;
    }
    const result = await api.campaigns(gameId);
    setCampaigns(result.campaigns);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("ruleshelf:theme", theme);
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#0f1115" : "#f6f2e9");
  }, [theme]);

  const toggleTheme = () => setTheme((current) => (current === "dark" ? "light" : "dark"));

  const setIncludeBgg = (value: boolean) => {
    setIncludeBggState(value);
    localStorage.setItem("ruleshelf:includeBgg", value ? "1" : "0");
  };

  // Restore the session before deciding which screen to show.
  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((result) => {
        if (!cancelled) setUser(result.user);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setAuthReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Any 401 from the API means the session expired or was revoked.
  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setUserMenuOpen(false);
      setPasswordOpen(false);
      setSettingsOpen(false);
    };
    window.addEventListener("ruleshelf:unauthorized", onUnauthorized);
    return () => window.removeEventListener("ruleshelf:unauthorized", onUnauthorized);
  }, []);

  // Initial load for the signed-in user.
  useEffect(() => {
    if (!user) return;
    setLoading(true);
    refreshLibrary()
      .catch((err: Error) => setLoadError(err.message))
      .finally(() => setLoading(false));
  }, [user, refreshLibrary]);

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
    Promise.all([refreshDocuments(activeGameId), refreshCampaigns(activeGameId)])
      .catch((err: Error) => notify(err.message, "error"))
      .finally(() => {
        if (!cancelled) setDocsLoading(false);
      });
    setHasSearched(false);
    setResults([]);
    setMeta(null);
    setAnswer("");
    setCommunityAnswer("");
    setCommunityStreaming(false);
    setCommunityError("");
    setSearchError("");
    setRoles([]);
    conversationRef.current = [];
    return () => {
      cancelled = true;
    };
  }, [activeGameId, refreshDocuments, refreshCampaigns, notify]);

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
    setCommunityAnswer("");
    setCommunityStreaming(false);
    setCommunityError("");
    setSearchError("");
    setEditingDoc(null);
  };

  const stopAsking = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setSearching(false);
    setCommunityStreaming(false);
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
    setCommunityAnswer("");
    setCommunityStreaming(false);
    setCommunityError("");
    setSearchError("");
    answerRef.current = "";
    communityRef.current = "";
    const scope = activeGameId && !searchAllGames ? activeGameId : undefined;

    if (!answerMode) {
      try {
        const response = await api.search({
          q: text,
          mode,
          game_id: scope,
          roles,
          limit: 30,
          include_bgg: includeBgg,
        });
        setResults(response.results);
        setMeta({
          mode_used: response.mode_used,
          note: response.note,
          embedding: response.embedding,
          bgg_count: response.bgg_count ?? 0,
          reddit_count: 0,
          bgg_note: response.bgg_note ?? null,
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
          include_bgg: includeBgg,
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
              bgg_count: payload.bgg_count ?? 0,
              bgg_note: payload.bgg_note ?? null,
            });
          },
          onToken: (token) => {
            answerRef.current += token;
            setAnswer(answerRef.current);
          },
          onError: (message) => setSearchError(message),
          onCommunitySearch: () => {
            communityRef.current = "";
            setCommunityAnswer("");
            setCommunityError("");
            setCommunityStreaming(true);
          },
          onCommunitySources: (payload) => {
            setResults((existing) => [...existing, ...payload.sources]);
            setMeta((existing) =>
              existing
                ? {
                    ...existing,
                    bgg_count: payload.bgg_count ?? 0,
                    reddit_count: payload.reddit_count ?? 0,
                    bgg_note: payload.note,
                  }
                : existing,
            );
          },
          onCommunityNote: (note) => {
            setMeta((existing) => (existing ? { ...existing, bgg_note: note } : existing));
            setCommunityStreaming(false);
          },
          onCommunityStart: () => {
            communityRef.current = "";
            setCommunityAnswer("");
            setCommunityError("");
            setCommunityStreaming(true);
          },
          onCommunityToken: (token) => {
            communityRef.current += token;
            setCommunityAnswer(communityRef.current);
          },
          onCommunityError: (message) => {
            setCommunityError(message);
            setCommunityStreaming(false);
          },
          onCommunityDone: () => setCommunityStreaming(false),
          onDone: () => {
            setSearching(false);
            setCommunityStreaming(false);
          },
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
            include_bgg: includeBgg,
          });
          setResults(fallback.results);
          setMeta({
            mode_used: fallback.mode_used,
            note: fallback.note,
            embedding: fallback.embedding,
            bgg_count: fallback.bgg_count ?? 0,
            reddit_count: 0,
            bgg_note: fallback.bgg_note ?? null,
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
    if (doc.is_image) {
      // Maps and handouts are viewed as images; OCR text is searchable separately.
      window.open(api.fileUrl(doc.id), "_blank", "noopener,noreferrer");
      return;
    }
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
    if ((result.source_type === "bgg" || result.source_type === "reddit") && result.url) {
      window.open(result.url, "_blank", "noopener,noreferrer");
      return;
    }
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
      await refreshCampaigns(null);
      navigate(null);
      notify("Game deleted.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const deleteDocument = async (doc: Document) => {
    const extra = doc.file_count
      ? ` and its ${doc.file_count} attached file${doc.file_count === 1 ? "" : "s"}`
      : "";
    if (
      !window.confirm(
        `Delete "${doc.title}"${extra}? This removes their index and files.`,
      )
    ) {
      return;
    }
    try {
      await api.deleteDocument(doc.id);
      await Promise.all([refreshDocuments(activeGameId), refreshCampaigns(activeGameId)]);
      await refreshLibrary();
      notify("Document deleted.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const ocrDocument = async (doc: Document) => {
    try {
      await api.ocrDocument(doc.id);
      await refreshDocuments(activeGameId);
      notify("OCR queued. Long books can take a while; progress is shown on the document.", "ok");
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

  const saveEditedDocument = async () => {
    await Promise.all([
      refreshDocuments(activeGameId),
      refreshCampaigns(activeGameId),
    ]);
    await refreshLibrary();
    setEditingDoc(null);
  };

  const deleteCampaign = async (campaign: Campaign) => {
    if (
      !window.confirm(
        `Delete the campaign "${campaign.title}"? Its documents are kept and become ungrouped.`,
      )
    ) {
      return;
    }
    try {
      await api.deleteCampaign(campaign.id);
      await Promise.all([refreshDocuments(activeGameId), refreshCampaigns(activeGameId)]);
      notify(`Campaign "${campaign.title}" removed; documents kept.`, "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const searchBusy = searching;

  const signOut = async () => {
    setUserMenuOpen(false);
    try {
      await api.logout();
    } catch {
      /* the session is cleared locally either way */
    }
    setUser(null);
    setGames([]);
    setDocuments([]);
    setCampaigns([]);
    setStats(null);
    setBundle(null);
    setResults([]);
    setAnswer("");
    setHasSearched(false);
    setActiveGameId(null);
    setSidebarOpen(false);
    window.location.hash = "#/";
  };

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
          communityAnswer={communityAnswer}
          communityStreaming={communityStreaming}
          communityError={communityError}
          error={searchError}
          onOpenResult={openReaderForResult}
          onStop={stopAsking}
          onConfigure={isAdmin ? () => setSettingsOpen(true) : undefined}
        />
      );
    }
    if (activeGame) {
      return (
        <GameView
          game={activeGame}
          gameType={activeGameType}
          documents={documents}
          campaigns={campaigns}
          embeddingConfigured={bundle?.info.embedding_ready ?? false}
          canWrite={isAdmin}
          onUpload={(role, campaignId, scenarioId) => {
            setUploadRole(role);
            setUploadCampaignId(campaignId ?? null);
            setUploadScenarioId(scenarioId ?? null);
          }}
          onEdit={() => setEditingGame(activeGame)}
          onDelete={deleteGame}
          onCampaignCreate={() => setCampaignDialog({})}
          onCampaignEdit={(campaign) => setCampaignDialog({ campaign })}
          onCampaignDelete={deleteCampaign}
          onOpenDoc={openReaderForDocument}
          onReindexDoc={reindexDocument}
          onOcrDoc={ocrDocument}
          onDeleteDoc={deleteDocument}
          onEditDoc={(doc) => setEditingDoc(doc)}
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
        canWrite={isAdmin}
        onOpenGame={(id) => navigate(id)}
        onNewGame={() => setAddGameOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
      />
    );
  };

  if (!authReady) {
    return (
      <div className="login-page">
        <span className="spinner large" />
      </div>
    );
  }

  if (!user) {
    return (
      <LoginPage
        theme={theme}
        onToggleTheme={toggleTheme}
        onLogin={(next) => {
          setLoadError("");
          setUser(next);
        }}
      />
    );
  }

  const isAdmin = user.role === "admin";

  return (
    <div className="app-shell">
      <Sidebar
        games={games}
        activeGameId={activeGameId}
        stats={stats}
        version={bundle?.info.version ?? "0.1.0"}
        open={sidebarOpen}
        canWrite={isAdmin}
        onSelect={navigate}
        onNewGame={() => {
          setSidebarOpen(false);
          setAddGameOpen(true);
        }}
        onSettings={() => {
          setSidebarOpen(false);
          setSettingsOpen(true);
        }}
        theme={theme}
        onToggleTheme={toggleTheme}
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
              setCommunityAnswer("");
              setCommunityStreaming(false);
              setCommunityError("");
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
            includeBgg={includeBgg}
            setIncludeBgg={setIncludeBgg}
          />
          <button
            className="icon-button topbar-theme"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            title={theme === "dark" ? "Light mode" : "Dark mode"}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={19} />
          </button>
          {isAdmin && (
            <button
              className="icon-button topbar-settings"
              onClick={() => setSettingsOpen(true)}
              aria-label="Settings"
              title="Settings"
            >
              <Icon name="settings" size={19} />
            </button>
          )}
          <div className="user-menu">
            <button
              className="icon-button topbar-user"
              onClick={() => setUserMenuOpen((open) => !open)}
              aria-label="Account menu"
              aria-expanded={userMenuOpen}
              title={user.email}
            >
              <Icon name="user" size={19} />
            </button>
            {userMenuOpen && (
              <>
                <div className="user-menu-scrim" onClick={() => setUserMenuOpen(false)} />
                <div className="user-menu-panel">
                  <div className="user-menu-id">
                    <strong>{user.email}</strong>
                    <small>{isAdmin ? "Administrator" : "Viewer"}</small>
                  </div>
                  <button
                    className="nav-item"
                    onClick={() => {
                      setUserMenuOpen(false);
                      setPasswordOpen(true);
                    }}
                  >
                    <Icon name="lock" size={16} />
                    <span>Change password</span>
                  </button>
                  <button className="nav-item" onClick={signOut}>
                    <Icon name="logout" size={16} />
                    <span>Sign out</span>
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        <main className="main">{mainContent()}</main>
      </div>

      <ReaderDrawer target={reader} onClose={() => setReader(null)} />

      {addGameOpen && isAdmin && (
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

      {editingDoc && isAdmin && (
        <EditDocumentDialog
          document={editingDoc}
          gameType={activeGameType}
          campaigns={campaigns}
          documents={documents}
          onClose={() => setEditingDoc(null)}
          onSaved={saveEditedDocument}
          notify={notify}
        />
      )}

      {editingGame && isAdmin && (
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

      {uploadRole && activeGame && isAdmin && (
        <UploadDialog
          game={activeGame}
          gameType={activeGameType}
          formats={bundle?.info.formats ?? []}
          maxUploadMb={bundle?.info.max_upload_mb ?? 512}
          campaigns={campaigns}
          documents={documents}
          initialRole={uploadRole}
          initialCampaignId={uploadCampaignId}
          initialScenarioId={uploadScenarioId}
          onClose={() => {
            setUploadRole(null);
            setUploadCampaignId(null);
            setUploadScenarioId(null);
          }}
          onUploaded={async () => {
            await Promise.all([
              refreshDocuments(activeGame.id),
              refreshCampaigns(activeGame.id),
            ]);
            const gameList = await api.games();
            setGames(gameList.games);
          }}
          notify={notify}
        />
      )}

      {campaignDialog && activeGame && isAdmin && (
        <CampaignDialog
          gameId={activeGame.id}
          campaign={campaignDialog.campaign}
          onClose={() => setCampaignDialog(null)}
          onSaved={async () => {
            await Promise.all([
              refreshCampaigns(activeGame.id),
              refreshDocuments(activeGame.id),
            ]);
            notify(campaignDialog.campaign ? "Campaign updated." : "Campaign created.", "ok");
          }}
        />
      )}

      {settingsOpen && isAdmin && bundle && providers && (
        <SettingsDialog
          bundle={bundle}
          providers={providers}
          currentUserId={user.id}
          onClose={() => setSettingsOpen(false)}
          onRefresh={refreshLibrary}
          notify={notify}
        />
      )}

      {passwordOpen && (
        <ChangePasswordDialog onClose={() => setPasswordOpen(false)} notify={notify} />
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
