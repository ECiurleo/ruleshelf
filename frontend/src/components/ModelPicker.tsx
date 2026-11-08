import { useEffect, useState } from "react";
import { api, type Provider } from "../lib/api";
import { Icon } from "./Icon";

export interface ModelChoice {
  providerId: string;
  model: string;
}

interface ModelOption extends ModelChoice {
  providerName: string;
}

/**
 * Lists chat models reported by every enabled provider, plus the configured
 * default. The empty value means "use the server default from Settings".
 */
export function ModelPicker({
  providers,
  value,
  defaultProvider,
  defaultModel,
  onChange,
}: {
  providers: Provider[];
  value: ModelChoice | null;
  defaultProvider: string;
  defaultModel: string;
  onChange: (value: ModelChoice | null) => void;
}) {
  const [options, setOptions] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Don't probe providers that cannot work yet (no key for a hosted API).
    const enabled = providers.filter(
      (provider) =>
        provider.enabled &&
        (provider.has_api_key || provider.kind === "ollama" || !provider.builtin),
    );
    if (!enabled.length) {
      setOptions([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.allSettled(
      enabled.map(async (provider) => ({
        provider,
        models: (await api.providerModels(provider.id)).models
          .filter((model) => model.kind !== "embedding")
          .map((model) => model.id),
      })),
    )
      .then((results) => {
        if (cancelled) return;
        const unique = new Set<string>();
        const next: ModelOption[] = [];
        results.forEach((result, index) => {
          const provider = enabled[index];
          let models: string[] =
            result.status === "fulfilled" ? result.value.models : [];
          if (provider.chat_model && !models.includes(provider.chat_model)) {
            models = [provider.chat_model, ...models];
          }
          for (const model of models) {
            const key = `${provider.id}|${model}`;
            if (unique.has(key)) continue;
            unique.add(key);
            next.push({ providerId: provider.id, providerName: provider.name, model });
          }
        });
        setOptions(next);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [providers]);

  const selected = value ? `${value.providerId}|${value.model}` : "";
  const selectedKnown =
    !value || options.some((option) => `${option.providerId}|${option.model}` === selected);
  const defaultLabel =
    defaultProvider && defaultModel
      ? `${defaultProvider} · ${defaultModel}`
      : "configured default";

  return (
    <label className="model-picker" title="Model used for Ask AI">
      <Icon name="sparkles" size={14} />
      <select
        value={selected}
        onChange={(event) => {
          if (!event.target.value) {
            onChange(null);
            return;
          }
          const separator = event.target.value.indexOf("|");
          onChange({
            providerId: event.target.value.slice(0, separator),
            model: event.target.value.slice(separator + 1),
          });
        }}
        aria-label="Answer model"
      >
        <option value="">Default · {defaultLabel}</option>
        {value && !selectedKnown && (
          <option value={selected}>
            {value.providerId} · {value.model}
          </option>
        )}
        {options.map((option) => (
          <option
            key={`${option.providerId}|${option.model}`}
            value={`${option.providerId}|${option.model}`}
          >
            {option.providerName} · {option.model}
          </option>
        ))}
      </select>
      {loading && <span className="spinner small" />}
    </label>
  );
}
