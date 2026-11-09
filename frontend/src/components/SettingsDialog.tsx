import { useEffect, useState } from "react";
import {
  api,
  type AppSettings,
  type ModelInfo,
  type ProviderList,
  type Job,
} from "../lib/api";
import { Modal } from "./Modal";
import { Icon } from "./Icon";
import { ProviderCard } from "./ProviderCard";
import { UsersTab } from "./UsersTab";

type Tab = "providers" | "search" | "types" | "users";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function SettingsDialog({
  bundle,
  providers,
  currentUserId,
  onClose,
  onRefresh,
  notify,
}: {
  bundle: AppSettings;
  providers: ProviderList;
  currentUserId: string;
  onClose: () => void;
  onRefresh: () => Promise<void>;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const [tab, setTab] = useState<Tab>("providers");

  return (
    <Modal
      title="Settings"
      subtitle={`${bundle.info.app_name} v${bundle.info.version} · data in ${bundle.info.data_dir}`}
      onClose={onClose}
      wide
    >
      <div className="tabs">
        <button className={tab === "providers" ? "selected" : ""} onClick={() => setTab("providers")}>
          AI providers
        </button>
        <button className={tab === "search" ? "selected" : ""} onClick={() => setTab("search")}>
          Search & answers
        </button>
        <button className={tab === "types" ? "selected" : ""} onClick={() => setTab("types")}>
          Game types
        </button>
        <button className={tab === "users" ? "selected" : ""} onClick={() => setTab("users")}>
          Users
        </button>
      </div>

      {tab === "providers" && (
        <ProvidersTab bundle={bundle} providers={providers} onRefresh={onRefresh} notify={notify} />
      )}
      {tab === "search" && (
        <SearchTab bundle={bundle} providers={providers} onRefresh={onRefresh} notify={notify} />
      )}
      {tab === "types" && (
        <TypesTab bundle={bundle} onRefresh={onRefresh} notify={notify} />
      )}
      {tab === "users" && <UsersTab currentUserId={currentUserId} notify={notify} />}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------
function ProvidersTab({
  bundle,
  providers,
  onRefresh,
  notify,
}: {
  bundle: AppSettings;
  providers: ProviderList;
  onRefresh: () => Promise<void>;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState(providers.drivers[0]?.kind ?? "openai_compat");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [chatModel, setChatModel] = useState("");
  const [embedModel, setEmbedModel] = useState("");
  const [busy, setBusy] = useState(false);
  const driver = providers.drivers.find((entry) => entry.kind === kind);

  const add = async () => {
    setBusy(true);
    try {
      const created = await api.createProvider({
        name: name.trim() || driver?.label || "Provider",
        kind,
        base_url: baseUrl.trim() || driver?.default_base_url || "",
        api_key: apiKey.trim(),
        chat_model: chatModel.trim(),
        embed_model: embedModel.trim(),
        description: driver?.description ?? "",
      });
      await onRefresh();
      notify(`${created.name} added.`, "ok");
      setAdding(false);
      setName("");
      setApiKey("");
      setChatModel("");
      setEmbedModel("");
    } catch (err) {
      notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tab-panel">
      <div className="tab-intro">
        <p>
          Bring your own model. Keys are stored only in this container's local database and are
          never sent anywhere except the provider you configure.
        </p>
        <button className="button ghost small" onClick={() => setAdding(!adding)}>
          <Icon name="plus" size={14} /> Add provider
        </button>
      </div>

      {adding && (
        <div className="add-provider">
          <div className="provider-grid">
            <label className="field">
              <span>API type</span>
              <select value={kind} onChange={(event) => setKind(event.target.value)}>
                {providers.drivers.map((entry) => (
                  <option key={entry.kind} value={entry.kind}>
                    {entry.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={driver?.label ?? "My provider"}
              />
            </label>
            <label className="field">
              <span>Base URL</span>
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder={driver?.default_base_url || "https://api.example.com/v1"}
              />
            </label>
            <label className="field">
              <span>API key</span>
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={driver?.requires_api_key ? "paste your key" : "not required"}
                autoComplete="off"
              />
            </label>
            <label className="field">
              <span>Chat model</span>
              <input
                value={chatModel}
                onChange={(event) => setChatModel(event.target.value)}
                placeholder="e.g. llama3.2"
              />
            </label>
            {driver?.supports_embeddings && (
              <label className="field">
                <span>Embedding model</span>
                <input
                  value={embedModel}
                  onChange={(event) => setEmbedModel(event.target.value)}
                  placeholder="e.g. nomic-embed-text"
                />
              </label>
            )}
          </div>
          <div className="add-provider-foot">
            <button className="button ghost small" onClick={() => setAdding(false)}>
              Cancel
            </button>
            <button className="button primary small" onClick={add} disabled={busy}>
              {busy ? <span className="spinner light" /> : "Add provider"}
            </button>
          </div>
        </div>
      )}

      <div className="provider-list">
        {providers.providers.map((provider) => (
          <ProviderCard
            key={provider.id}
            provider={provider}
            driver={providers.drivers.find((entry) => entry.kind === provider.kind)}
            onChanged={onRefresh}
            notify={notify}
          />
        ))}
      </div>

      <p className="fine-print">
        Adding a brand-new API dialect? Drop a driver file in{" "}
        <code>backend/app/providers/</code>; it appears in this list on restart.
      </p>
      <p className="fine-print">Current default chat provider: {bundle.info.provider_names[bundle.settings.default_chat_provider] ?? "none"}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search & answers
// ---------------------------------------------------------------------------
function SearchTab({
  bundle,
  providers,
  onRefresh,
  notify,
}: {
  bundle: AppSettings;
  providers: ProviderList;
  onRefresh: () => Promise<void>;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const settings = bundle.settings;
  const enabled = providers.providers.filter((provider) => provider.enabled);
  const [chatProvider, setChatProvider] = useState(settings.default_chat_provider ?? "");
  const [chatModel, setChatModel] = useState(settings.default_chat_model ?? "");
  const [embedProvider, setEmbedProvider] = useState(settings.embedding_provider ?? "");
  const [embedModel, setEmbedModel] = useState(settings.embedding_model ?? "");
  const [topK, setTopK] = useState(settings.rag_top_k ?? "10");
  const [temperature, setTemperature] = useState(settings.rag_temperature ?? "0.2");
  const [systemPrompt, setSystemPrompt] = useState(settings.system_prompt ?? "");
  const [redditEnabled, setRedditEnabled] = useState(
    settings.reddit_enabled !== "0",
  );
  const [chatModels, setChatModels] = useState<ModelInfo[]>([]);
  const [embedModels, setEmbedModels] = useState<ModelInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [force, setForce] = useState(false);

  useEffect(() => {
    if (!chatProvider) return;
    api
      .providerModels(chatProvider)
      .then((result) => setChatModels(result.models))
      .catch(() => setChatModels([]));
  }, [chatProvider]);

  useEffect(() => {
    if (!embedProvider) return;
    api
      .providerModels(embedProvider)
      .then((result) => setEmbedModels(result.models))
      .catch(() => setEmbedModels([]));
  }, [embedProvider]);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await api.job(job.id);
        setJob(next);
        if (next.status === "done") {
          notify(next.message, "ok");
          await onRefresh();
        }
        if (next.status === "error") notify(next.message, "error");
      } catch (err) {
        notify((err as Error).message, "error");
      }
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [job, notify, onRefresh]);

  const save = async () => {
    setBusy(true);
    try {
      await api.updateSettings({
        default_chat_provider: chatProvider,
        default_chat_model: chatModel,
        embedding_provider: embedProvider,
        embedding_model: embedModel,
        rag_top_k: Number(topK) || 10,
        rag_temperature: Number(temperature) || 0,
        system_prompt: systemPrompt,
        reddit_enabled: redditEnabled,
      });
      await onRefresh();
      notify("Settings saved.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const startEmbedding = async () => {
    try {
      const started = await api.buildEmbeddings({ force });
      setJob({
        id: started.job_id,
        kind: "embed",
        status: "queued",
        progress: 0,
        message: "Queued",
        result: "",
      });
      notify("Embedding job started.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const chatProviderRow = providers.providers.find((entry) => entry.id === chatProvider);
  const embedProviderRow = providers.providers.find((entry) => entry.id === embedProvider);

  return (
    <div className="tab-panel">
      <div className={`banner ${bundle.info.embedding_ready ? "subtle" : ""}`}>
        <Icon name="sparkles" size={17} />
        <div>
          {bundle.info.embedding_ready ? (
            <>
              <strong>Semantic search is ready</strong> using{" "}
              {bundle.info.provider_names[settings.embedding_provider] ?? "your provider"} ·{" "}
              {bundle.info.embedding_model_active}. New documents embed automatically.
            </>
          ) : (
            <>
              <strong>Semantic search is off.</strong>{" "}
              {bundle.info.embedding_error ?? "Choose an embedding provider below."}
            </>
          )}
        </div>
      </div>

      <section className="settings-section">
        <h3>Answering</h3>
        <div className="provider-grid">
          <label className="field">
            <span>Chat provider</span>
            <select value={chatProvider} onChange={(event) => setChatProvider(event.target.value)}>
              <option value="">— none —</option>
              {enabled.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Chat model</span>
            <input
              value={chatModel}
              onChange={(event) => setChatModel(event.target.value)}
              list="settings-chat-models"
              placeholder={chatProviderRow?.chat_model || "type or load a model"}
            />
            <datalist id="settings-chat-models">
              {chatModels.map((model) => (
                <option key={model.id} value={model.id} />
              ))}
            </datalist>
          </label>
          <label className="field">
            <span>Excerpts per answer</span>
            <input
              type="number"
              min={1}
              max={30}
              value={topK}
              onChange={(event) => setTopK(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Temperature</span>
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={temperature}
              onChange={(event) => setTemperature(event.target.value)}
            />
          </label>
        </div>
        <label className="field">
          <span>Referee instructions <small>· the system prompt</small></span>
          <textarea
            rows={5}
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
          />
        </label>
      </section>

      <section className="settings-section">
        <h3>Community search</h3>
        <p className="fine-print">
          BoardGameGeek threads and Reddit posts are found through plain web search. No
          account, API key or password is needed. Community results are always marked
          unofficial; rulebook excerpts are ranked first and the referee answer never uses
          them.
        </p>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={redditEnabled}
            onChange={(event) => setRedditEnabled(event.target.checked)}
          />
          Search Reddit as well as BoardGameGeek
        </label>
      </section>

      <section className="settings-section">
        <h3>Meaning search</h3>
        <div className="provider-grid">
          <label className="field">
            <span>Embedding provider</span>
            <select
              value={embedProvider}
              onChange={(event) => {
                const next = event.target.value;
                setEmbedProvider(next);
                const row = providers.providers.find((provider) => provider.id === next);
                setEmbedModel(row?.embed_model ?? "");
              }}
            >
              <option value="">— none —</option>
              {enabled
                .filter((provider) =>
                  providers.drivers.find(
                    (entry) => entry.kind === provider.kind && entry.supports_embeddings,
                  ),
                )
                .map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
            </select>
          </label>
          <label className="field">
            <span>Embedding model</span>
            <input
              value={embedModel}
              onChange={(event) => setEmbedModel(event.target.value)}
              list="settings-embed-models"
              placeholder={embedProviderRow?.embed_model || "e.g. nomic-embed-text"}
            />
            <datalist id="settings-embed-models">
              {embedModels.map((model) => (
                <option key={model.id} value={model.id} />
              ))}
            </datalist>
          </label>
        </div>

        <div className="embed-actions">
          <label className="checkbox">
            <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
            Re-embed everything (needed if you changed model)
          </label>
          <button
            className="button ghost small"
            onClick={startEmbedding}
            disabled={!bundle.info.embedding_ready && !force}
          >
            <Icon name="sparkles" size={14} /> Build embeddings
          </button>
        </div>

        {job && (
          <div className="job">
            <div className="job-bar">
              <span style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
            </div>
            <p>
              {job.message} {job.status === "error" ? "" : `(${Math.round(job.progress * 100)}%)`}
            </p>
          </div>
        )}
      </section>

      <div className="settings-actions">
        <button className="button primary" onClick={save} disabled={busy}>
          {busy ? <span className="spinner light" /> : null}
          Save settings
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Game types
// ---------------------------------------------------------------------------
function TypesTab({
  bundle,
  onRefresh,
  notify,
}: {
  bundle: AppSettings;
  onRefresh: () => Promise<void>;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const [types, setTypes] = useState<Awaited<ReturnType<typeof api.gameTypes>>["game_types"]>([]);
  const [label, setLabel] = useState("");
  const [roles, setRoles] = useState("core: Core rules\nexpansion: Supplement\ncampaign: Campaign");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const result = await api.gameTypes();
    setTypes(result.game_types);
  };

  useEffect(() => {
    load().catch((err: Error) => notify(err.message, "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const add = async () => {
    const parsed = roles
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [idPart, ...labelParts] = line.split(":");
        const roleLabel = labelParts.join(":").trim() || idPart.trim();
        return { id: slugify(idPart), label: roleLabel };
      })
      .filter((role) => role.id);
    if (!label.trim() || !parsed.length) {
      notify("Give the type a label and at least one role.", "error");
      return;
    }
    setBusy(true);
    try {
      await api.createGameType({
        id: slugify(label),
        label: label.trim(),
        description: "",
        roles: parsed,
      });
      setLabel("");
      await load();
      await onRefresh();
      notify("Game type added.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(`Delete the game type "${id}"?`)) return;
    try {
      await api.deleteGameType(id);
      await load();
      notify("Game type removed.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  return (
    <div className="tab-panel">
      <div className="type-table">
        {types.map((type) => (
          <div className="type-row" key={type.id}>
            <div>
              <strong>{type.label}</strong>
              <span className="provider-kind">{type.id}</span>
            </div>
            <div className="type-row-roles">
              {type.roles.map((role) => (
                <span className="chip static tiny" key={role.id}>
                  {role.label}
                </span>
              ))}
            </div>
            <span className="type-row-count">{type.game_count} games</span>
            {!type.builtin && (
              <button
                className="icon-button danger"
                onClick={() => remove(type.id)}
                disabled={type.game_count > 0}
                title={type.game_count > 0 ? "In use" : "Delete"}
              >
                <Icon name="trash" size={15} />
              </button>
            )}
          </div>
        ))}
      </div>

      <section className="settings-section">
        <h3>Add a custom type</h3>
        <div className="provider-grid">
          <label className="field">
            <span>Label</span>
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="e.g. Skirmish game"
            />
          </label>
          <label className="field grow">
            <span>Roles <small>· one per line, <code>id: Label</code></small></span>
            <textarea rows={4} value={roles} onChange={(event) => setRoles(event.target.value)} />
          </label>
        </div>
        <button className="button primary small" onClick={add} disabled={busy}>
          {busy ? <span className="spinner light" /> : <Icon name="plus" size={14} />} Add type
        </button>
      </section>

      <p className="fine-print">
        Built-in types ship with the app. Custom types are stored in the local database and can be
        deleted while unused.
      </p>
      <p className="fine-print">
        Data directory: <code>{bundle.info.data_dir}</code>
      </p>
      <p className="fine-print">
        Configuration snapshot: <code>{bundle.info.config_file}</code> — written on every change and
        re-applied at startup.
      </p>
    </div>
  );
}
