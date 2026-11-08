import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { SearchResult } from "../lib/api";
import { Icon } from "./Icon";

function ResultCard({ result, onOpen }: { result: SearchResult; onOpen: () => void }) {
  return (
    <article className="result-card" onClick={onOpen}>
      <div className="result-meta">
        <span className={`type-badge type-${result.game.game_type}`}>{result.game.title}</span>
        <span className="result-doc">{result.document.title}</span>
        <span className="dot-sep" />
        <span>{result.document.role_label}</span>
        {result.page_start && (
          <>
            <span className="dot-sep" />
            <span>
              {result.page_end && result.page_end !== result.page_start
                ? `pp. ${result.page_start}–${result.page_end}`
                : `p. ${result.page_start}`}
            </span>
          </>
        )}
        <span className="result-open">
          <Icon name="chevron" size={15} />
        </span>
      </div>
      <p className="result-snippet" dangerouslySetInnerHTML={{ __html: result.snippet }} />
    </article>
  );
}

export function ResultsView({
  query,
  results,
  meta,
  askMode,
  asking,
  answer,
  error,
  onOpenResult,
  onStop,
  onConfigure,
}: {
  query: string;
  results: SearchResult[];
  meta: { mode_used: string; note: string | null; provider?: string; model?: string } | null;
  askMode: boolean;
  asking: boolean;
  answer: string;
  error: string;
  onOpenResult: (result: SearchResult) => void;
  onStop: () => void;
  onConfigure: () => void;
}) {
  const showAnswer = askMode && (asking || answer || error);

  // Make [n] citations clickable; the server also appends a References block
  // linking each source to its document page.
  const renderedAnswer = answer.replace(/\[(\d{1,2})\]/g, (match, value: string) => {
    const index = Number(value);
    return index >= 1 && index <= results.length ? `[${index}](#ref-${index})` : match;
  });

  const markdownComponents: Components = {
    a({ href, children }) {
      if (href?.startsWith("#ref-")) {
        const index = Number(href.slice(5)) - 1;
        const result = results[index];
        if (result) {
          return (
            <button
              type="button"
              className="citation-chip"
              title={`${result.document.title}${
                result.page_start ? `, p. ${result.page_start}` : ""
              }`}
              onClick={() => onOpenResult(result)}
            >
              {children}
            </button>
          );
        }
      }
      if (href?.startsWith("/api/documents/")) {
        const documentId = href.match(/^\/api\/documents\/([^/]+)\/file/)?.[1];
        const page = href.match(/#page=(\d+)/)?.[1];
        const source = results.find(
          (result) =>
            result.document.id === documentId &&
            (!page || result.page_start === Number(page)),
        );
        if (source) {
          return (
            <button
              type="button"
              className="reference-link"
              onClick={() => onOpenResult(source)}
            >
              {children}
            </button>
          );
        }
      }
      return (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
  };

  const hasReferences = /references/i.test(answer);

  return (
    <div className="view results-view">
      <div className="results-heading">
        <div>
          <p className="eyebrow">{askMode ? "Answer" : "Search results"}</p>
          <h2>{query}</h2>
        </div>
        {meta && (
          <div className="results-mode">
            <span className="chip static">
              {meta.mode_used === "hybrid"
                ? "Smart"
                : meta.mode_used === "semantic"
                  ? "Meaning"
                  : "Keyword"}
            </span>
            {meta.provider && (
              <span className="results-provider">
                {meta.provider} · {meta.model}
              </span>
            )}
          </div>
        )}
      </div>

      {meta?.note && (
        <div className="banner subtle">
          <Icon name="alert" size={17} />
          <div>{meta.note}</div>
          <button className="button ghost small" onClick={onConfigure}>
            Settings
          </button>
        </div>
      )}

      {error && (
        <div className="banner error">
          <Icon name="alert" size={17} />
          <div>{error}</div>
          <button className="button ghost small" onClick={onConfigure}>
            Check providers
          </button>
        </div>
      )}

      {showAnswer && (
        <section className="answer-panel">
          <div className="answer-head">
            <span className="answer-icon">
              <Icon name="sparkles" size={17} />
            </span>
            <span>Referee's answer</span>
            {asking && (
              <button className="button ghost small" onClick={onStop}>
                Stop
              </button>
            )}
          </div>
          <div className="answer-body">
            {answer ? (
              <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {renderedAnswer}
              </Markdown>
            ) : asking ? (
              <p className="thinking">
                <span className="spinner" /> Consulting your rulebooks…
              </p>
            ) : null}
            {asking && answer && <span className="cursor" />}
            {answer && results.length > 0 && !hasReferences && !asking && (
              <div className="answer-references">
                <h4>References</h4>
                <ol>
                  {results.map((result) => (
                    <li key={result.chunk_id}>
                      <button
                        type="button"
                        className="reference-link"
                        onClick={() => onOpenResult(result)}
                      >
                        {result.document.title}
                        {result.page_start ? `, p. ${result.page_start}` : ""} —{" "}
                        {result.game.title}
                      </button>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
          <p className="answer-hint">
            Answers are generated from the excerpts below. Always check the cited page at the
            table.
          </p>
        </section>
      )}

      {results.length > 0 && (
        <section className="source-list">
          <h3>
            {askMode ? "Sources" : `${results.length} ${results.length === 1 ? "match" : "matches"}`}
          </h3>
          {results.map((result, index) => (
            <div className="source-row" key={result.chunk_id}>
              {askMode && <span className="source-number">{index + 1}</span>}
              <ResultCard result={result} onOpen={() => onOpenResult(result)} />
            </div>
          ))}
        </section>
      )}

      {!asking && !error && results.length === 0 && (
        <div className="empty-panel compact">
          <span className="empty-mark">
            <Icon name="search" size={26} />
          </span>
          <h2>No matches</h2>
          <p>
            Try fewer words, a different mode, or a broader role filter. Keyword search needs the
            exact term; meaning search needs the library to be embedded.
          </p>
        </div>
      )}
    </div>
  );
}
