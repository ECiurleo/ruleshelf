import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { SearchResult } from "../lib/api";
import { Icon } from "./Icon";

function ResultCard({ result, onOpen }: { result: SearchResult; onOpen: () => void }) {
  const errata = result.document.overrides;
  const forum = result.source_type === "bgg" || result.source_type === "reddit";
  const forumLabel = result.source_type === "reddit" ? "Reddit · unofficial" : "BGG forum · unofficial";
  return (
    <article className={`result-card ${errata ? "errata" : ""} ${forum ? "bgg" : ""}`} onClick={onOpen}>
      <div className="result-meta">
        <span className={`type-badge type-${result.game.game_type}`}>{result.game.title}</span>
        <span className="result-doc">{result.document.title}</span>
        <span className="dot-sep" />
        {forum ? (
          <span className="forum-flag">{forumLabel}</span>
        ) : errata ? (
          <span className="errata-flag">Errata · overrides core rules</span>
        ) : (
          <span>{result.document.role_label}</span>
        )}
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
          <Icon name={forum ? "external" : "chevron"} size={15} />
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
  answerMode,
  asking,
  answer,
  communityAnswer,
  communityStreaming,
  communityError,
  error,
  onOpenResult,
  onStop,
  onConfigure,
}: {
  query: string;
  results: SearchResult[];
  meta: {
    mode_used: string;
    note: string | null;
    provider?: string;
    model?: string;
    embedding?: { provider_name: string; model: string } | null;
    bgg_count?: number;
    reddit_count?: number;
    bgg_note?: string | null;
  } | null;
  answerMode: boolean;
  asking: boolean;
  answer: string;
  communityAnswer?: string;
  communityStreaming?: boolean;
  communityError?: string;
  error: string;
  onOpenResult: (result: SearchResult) => void;
  onStop: () => void;
  onConfigure?: () => void;
}) {
  const showAnswer = answerMode && (asking || answer || error);

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
  const showCommunity = Boolean(
    answerMode && (communityAnswer || communityStreaming || communityError),
  );
  const renderedCommunity = (communityAnswer ?? "").replace(
    /\[(\d{1,2})\]/g,
    (match, value: string) => {
      const index = Number(value);
      return index >= 1 && index <= results.length ? `[${index}](#ref-${index})` : match;
    },
  );

  return (
    <div className="view results-view">
      <div className="results-heading">
        <div>
          <p className="eyebrow">{answerMode ? "Answer" : "Search results"}</p>
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
              <span className="model-usage" title="Model that wrote this answer">
                <Icon name="sparkles" size={14} />
                <span>
                  <small>Answer model</small>
                  {meta.provider} · {meta.model}
                </span>
              </span>
            )}
            {meta.embedding && (
              <span className="model-usage subtle" title="Model used to find passages">
                <Icon name="search" size={14} />
                <span>
                  <small>Embedding model</small>
                  {meta.embedding.provider_name} · {meta.embedding.model}
                </span>
              </span>
            )}
            {(meta.bgg_count ?? 0) > 0 || (meta.reddit_count ?? 0) > 0 ? (
              <span
                className="forum-flag"
                title="Unofficial community forum results"
              >
                Community ·{" "}
                {[
                  (meta.bgg_count ?? 0) > 0 ? `BGG ${meta.bgg_count}` : null,
                  (meta.reddit_count ?? 0) > 0 ? `Reddit ${meta.reddit_count}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            ) : null}
          </div>
        )}
      </div>

      {meta?.note && (
        <div className="banner subtle">
          <Icon name="alert" size={17} />
          <div>{meta.note}</div>
          {onConfigure && (
            <button className="button ghost small" onClick={onConfigure}>
              Settings
            </button>
          )}
        </div>
      )}

      {meta?.bgg_note && (
        <div className="banner subtle">
          <Icon name="external" size={17} />
          <div>{meta.bgg_note} Rulebook answers are unaffected.</div>
        </div>
      )}

      {error && (
        <div className="banner error">
          <Icon name="alert" size={17} />
          <div>{error}</div>
          {onConfigure && (
            <button className="button ghost small" onClick={onConfigure}>
              Check providers
            </button>
          )}
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

      {showCommunity && (
        <section className="answer-panel community-answer">
          <div className="answer-head community-head">
            <span className="answer-icon">
              <Icon name="external" size={17} />
            </span>
            <span>Community Answer</span>
            <span className="community-badge">Unofficial · BGG forums</span>
            {communityStreaming && <span className="spinner" />}
          </div>
          <div className="answer-body">
            {communityAnswer ? (
              <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {renderedCommunity}
              </Markdown>
            ) : communityStreaming ? (
              <p className="thinking">
                <span className="spinner" /> Reading BoardGameGeek threads…
              </p>
            ) : null}
            {communityStreaming && communityAnswer && <span className="cursor" />}
          </div>
          {communityError && <p className="community-error">{communityError}</p>}
          <p className="answer-hint">
            Community posts are not rules text. The rulebook answer above takes precedence.
          </p>
        </section>
      )}

      {results.length > 0 && (
        <section className="source-list">
          <h3>
            {answerMode ? "Sources" : `${results.length} ${results.length === 1 ? "match" : "matches"}`}
          </h3>
          {results.map((result, index) => (
            <div className="source-row" key={result.chunk_id}>
              {answerMode && <span className="source-number">{index + 1}</span>}
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
