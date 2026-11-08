import { useState } from "react";
import { api, type Driver, type ModelInfo, type Provider } from "../lib/api";
import { Icon } from "./Icon";

export function ProviderCard({
  provider,
  driver,
  onChanged,
  notify,
}: {
  provider: Provider;
  driver: Driver | undefined;
  onChanged: () => Promise<void> | void;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const [name, setName] = useState(provider.name);
  const [baseUrl, setBaseUrl] = useState(provider.base_url);
  const [apiKey, setApiKey] = useState("");
  const [chatModel, setChatModel] = useState(provider.chat_model);
  const [embedModel, setEmbedModel] = useState(provider.embed_model);
  const [enabled, setEnabled] = useState(provider.enabled);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const supportsEmbeddings = driver?.supports_embeddings ?? Boolean(provider.embed_model);

  const save = async (extra: Record<string, unknown> = {}) => {
    setBusy(true);
    setMessage(null);
    try {
      await api.updateProvider(provider.id, {
        name: name.trim(),
        base_url: baseUrl.trim(),
        chat_model: chatModel.trim(),
        embed_model: embedModel.trim(),
        enabled,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        ...extra,
      });
      setApiKey("");
      await onChanged();
      setMessage({ ok: true, text: "Saved." });
      notify(`${name.trim()} saved.`, "ok");
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.testProvider(provider.id);
      setMessage({ ok: result.ok, text: result.message });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const loadModels = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.providerModels(provider.id);
      setModels(result.models);
      setMessage({
        ok: true,
        text: `Found ${result.count} models. Pick one below or type an id.`,
      });
      if (!chatModel) {
        const firstChat = result.models.find((model) => model.kind === "chat");
        if (firstChat) setChatModel(firstChat.id);
      }
      if (!embedModel) {
        const firstEmbed = result.models.find((model) => model.kind === "embedding");
        if (firstEmbed) setEmbedModel(firstEmbed.id);
      }
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Remove the provider "${provider.name}"?`)) return;
    try {
      await api.deleteProvider(provider.id);
      await onChanged();
      notify("Provider removed.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const toggleEnabled = async () => {
    const next = !enabled;
    setEnabled(next);
    try {
      await api.updateProvider(provider.id, { enabled: next });
      await onChanged();
    } catch (err) {
      setEnabled(!next);
      notify((err as Error).message, "error");
    }
  };

  return (
    <article className={`provider-card ${enabled ? "" : "disabled"}`}>
      <header className="provider-head">
        <div className="provider-title">
          <strong>{provider.name}</strong>
          <span className="provider-kind">{driver?.label ?? provider.kind}</span>
          {provider.builtin && <span className="chip static tiny">built in</span>}
        </div>
        <div className="provider-head-actions">
          {provider.docs_url && (
            <a
              className="link-button"
              href={provider.docs_url}
              target="_blank"
              rel="noreferrer"
              title="Get an API key"
            >
              API keys <Icon name="external" size={13} />
            </a>
          )}
          <label className="switch" title={enabled ? "Disable provider" : "Enable provider"}>
            <input type="checkbox" checked={enabled} onChange={toggleEnabled} />
            <span />
          </label>
        </div>
      </header>

      {provider.description && <p className="provider-description">{provider.description}</p>}

      <div className="provider-grid">
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="field">
          <span>Base URL</span>
          <input
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder={driver?.default_base_url || "https://…"}
          />
        </label>
        <label className="field">
          <span>
            API key {provider.has_api_key && <small>· saved, leave blank to keep</small>}
          </span>
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={
              provider.has_api_key
                ? "••••••••"
                : driver?.requires_api_key === false
                  ? "not required"
                  : "paste your key"
            }
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span>Chat model</span>
          <input
            value={chatModel}
            onChange={(event) => setChatModel(event.target.value)}
            list={`chat-models-${provider.id}`}
            placeholder="e.g. llama3.2"
          />
          <datalist id={`chat-models-${provider.id}`}>
            {models
              .filter((model) => model.kind !== "embedding")
              .map((model) => (
                <option key={model.id} value={model.id} />
              ))}
          </datalist>
        </label>
        {supportsEmbeddings && (
          <label className="field">
            <span>Embedding model <small>· for meaning search</small></span>
            <input
              value={embedModel}
              onChange={(event) => setEmbedModel(event.target.value)}
              list={`embed-models-${provider.id}`}
              placeholder="e.g. nomic-embed-text"
            />
            <datalist id={`embed-models-${provider.id}`}>
              {models
                .filter((model) => model.kind === "embedding")
                .map((model) => (
                  <option key={model.id} value={model.id} />
                ))}
            </datalist>
          </label>
        )}
      </div>

      {message && (
        <p className={`provider-message ${message.ok ? "ok" : "error"}`}>{message.text}</p>
      )}

      <footer className="provider-foot">
        <button className="button ghost small" onClick={loadModels} disabled={busy}>
          <Icon name="refresh" size={14} /> Load models
        </button>
        <button className="button ghost small" onClick={test} disabled={busy}>
          <Icon name="check" size={14} /> Test
        </button>
        {!provider.builtin && (
          <button className="button ghost small danger" onClick={remove} disabled={busy}>
            <Icon name="trash" size={14} /> Remove
          </button>
        )}
        <span className="provider-spacer" />
        <button className="button primary small" onClick={() => save()} disabled={busy}>
          {busy ? <span className="spinner light" /> : "Save"}
        </button>
      </footer>
    </article>
  );
}
