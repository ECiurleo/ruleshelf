# Ruleshelf

**Every rule, right where you need it.** Ruleshelf is a self-hosted library and search engine for
tabletop rulebooks — roleplaying games, board games and wargames. Search by keyword or by meaning,
or ask a question and get an answer with citations back to the exact page.

```bash
docker compose up -d      # then open http://localhost:8080
```

![Ruleshelf library](docs/screenshots/library.png)

## What it does

- **One shelf per game.** Each game has a typed structure: a core rule set (the primary source),
  supplements/expansions (bestiaries, army books) and campaigns (separate from the rules).
- **Uploads stay yours.** PDFs, EPUB, DOCX, Markdown, text and HTML are stored on disk and indexed
  into a local SQLite database. Nothing leaves your machine unless you call an AI provider.
- **Errata wins.** File official corrections under **Errata**: they are boosted above the core rules
  in every search mode, flagged with an "overrides core rules" badge, and the AI is instructed to
  treat them as superseding where the texts conflict. Every answer says when errata took precedence.
- **Three search modes.**
  - *Keyword* — SQLite FTS5, exact words, names and table entries.
  - *Meaning* — vector search over your embedding model.
  - *Smart* — hybrid keyword + vector ranking (reciprocal rank fusion).
- **Ask the rules.** Retrieval-augmented answers stream from the AI provider you choose. Every
  answer ends with a References block listing the document, page and a link to the source, and each
  inline `[n]` citation is clickable straight into the in-app reader.
- **Reader built in.** Open any result in a drawer, read the page, jump to the original PDF at that
  page, or download the file.
- **Bring your own model.** Built-in support for **Ollama** (free/local), **OpenAI/ChatGPT**,
  **Anthropic Claude**, **DeepSeek** and **Qwen/DashScope**, plus any OpenAI-compatible endpoint
  (OpenRouter, LM Studio, vLLM, LiteLLM, Azure gateways…). Adding another API dialect is one file.
- **Data-driven game types.** Built-in RPG / board game / wargame types, and custom types with
  custom roles can be added in Settings.
- **One container, one volume.** ~0.2 GB image, multi-arch (`amd64` and `arm64`).

![Asking a rules question with linked references](docs/screenshots/answer.png)

## Quick start

The published image lives at `ghcr.io/eciurleo/ruleshelf`.

```bash
# with the compose file from this repo
docker compose up -d
# or plain Docker
docker run -d --name ruleshelf \
  -p 8080:8000 \
  -v ruleshelf-data:/data \
  --add-host=host.docker.internal:host-gateway \
  ghcr.io/eciurleo/ruleshelf:latest
```

Open <http://localhost:8080>. Add a game, upload its core rulebook, and start searching.

To upgrade:

```bash
docker compose pull && docker compose up -d
```

To build the image yourself instead of pulling:

```bash
docker compose -f compose.dev.yml up -d --build
```

## Setting up AI

Keyword search works with no configuration at all. Meaning search and *Ask AI* need a provider.

**Option A — local and free (Ollama)**

```bash
ollama pull nomic-embed-text     # embeddings, ~275 MB
ollama pull llama3.2             # a chat model, optional
```

In Ruleshelf: **Settings → AI providers → Ollama**, set the base URL and models, **Save**, then
**Load models → Test**. For the compose setup the URL is already
`http://host.docker.internal:11434`. If Ollama runs on another machine, point the URL there.

**Option B — hosted**

Add your own key for OpenAI, Anthropic, DeepSeek or Qwen in the same screen. Then in
**Settings → Search & answers**, choose the default chat provider/model and the embedding
provider/model. Claude has no embedding model; pair it with Ollama or OpenAI for vectors.

After choosing an embedding model for an existing library, run **Build embeddings** with
*Re-embed everything* ticked. New documents embed automatically.

> API keys are written to the local SQLite database inside the volume. They are never returned by
> the API in plain text and never sent anywhere except the provider you configured.

## How the library is organised

| Level | Examples |
| --- | --- |
| Game | *Warhammer Fantasy Roleplay 4e* — type: RPG |
| └ Core rules | *Warhammer Fantasy Core Rules* — the primary source |
| └ Errata | *Core Rules Errata v1.2* — corrections that override the core rules |
| └ Supplements | *The Imperial Zoo*, *Altdorf: Crown of the Empire* |
| └ Campaigns | *The Enemy Within* |
| Game | *Warhammer: The Old World* — type: Wargame |
| └ Core rules | *Core Rulebook* |
| └ Army books | *Arcane Journal: Kingdom of Bretonnia* |

Roles are per game type and can be changed (or new types added) in **Settings → Game types**.
A role can carry a `precedence` value; errata ships with `100`, which boosts it above normal rules
and marks its results as overriding.

![A game shelf with core rules, supplements and a campaign](docs/screenshots/game.png)

## Search tips

- `"exact phrase"` searches a phrase; other words are AND-ed and the last word is prefix-matched.
- Filter by role (core / errata / supplements / campaigns) to keep campaign spoilers out of rules answers.
- Errata is prioritised over the core rules automatically; add precedence to any custom role in
  **Settings → Game types** if your game uses a different source of corrections.
- *Meaning* search finds “wizard spell goes wrong” even when the book says “miscast”.
- The reader shows the indexed page; the **Original** button opens the PDF at that page.

## Supported files

| Format | Notes |
| --- | --- |
| `.pdf` | Needs a text layer. Scanned books must be OCR'd first (`ocrmypdf in.pdf out.pdf`). |
| `.epub` | One citable unit per chapter. |
| `.docx` | Grouped by heading. |
| `.txt`, `.md`, `.rst` | A form feed (`\f`) starts a new page. |
| `.html`, `.htm` | Readable text is extracted. |

Maximum upload size is 512 MB per file (`RULESHELF_MAX_UPLOAD_MB` to change it).

## Data, backup and privacy

Everything lives in the mounted volume (`/data` by default):

```
/data/ruleshelf.db   SQLite: library, FTS index, embeddings, settings, provider keys
/data/files/         your uploaded documents, untouched
```

Back up by copying the volume, or:

```bash
docker run --rm -v ruleshelf-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/ruleshelf-backup.tgz -C /data .
```

Ruleshelf has no accounts and no outbound telemetry. Bind it to `127.0.0.1` (or put it behind your
own reverse proxy) if the machine is shared — anyone who can reach the port can use the library.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `RULESHELF_DATA_DIR` | `/data` in the image | Database and uploaded files. |
| `RULESHELF_OLLAMA_URL` | `http://host.docker.internal:11434` in Docker | Default Ollama address seeded for new installs. |
| `RULESHELF_MAX_UPLOAD_MB` | `512` | Per-file upload limit. |
| `RULESHELF_CHUNK_SIZE` / `..._OVERLAP` | `1100` / `160` | Indexing window. Re-index documents after changing. |
| `RULESHELF_HOST` / `..._PORT` | `0.0.0.0` / `8000` | Only for `python -m app`. |

## Development

Requirements: Python 3.12, Node 22.

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://localhost:8000, data in ./backend/data

# frontend (second terminal)
cd frontend
npm install
npm run dev                            # http://localhost:5173, proxies /api
```

```bash
cd backend && pytest -q && ruff check app tests
cd frontend && npm run build
```

The API is documented at <http://localhost:8000/docs>.

### Project layout

```
backend/app/
  api/           HTTP routers: games, documents, search/ask, providers, settings
  services/      ingestion, chunking, retrieval, embeddings, RAG, background jobs
  providers/     AI drivers + auto-discovered registry
  extractors/    file-format drivers + auto-discovered registry
  db.py          schema, migrations, seed data
frontend/src/
  components/    UI: library, game view, search, reader, settings
  lib/api.ts     typed API client and SSE streaming
Dockerfile       multi-stage: Vite build + FastAPI runtime
```

### Extending it

**A new AI provider type** (if it is not OpenAI-compatible):

```python
# backend/app/providers/my_api.py
from app.providers.base import ModelInfo, Provider
from app.providers import register_driver

class MyProvider(Provider):
    kind = "my_api"

    def list_models(self):
        return [ModelInfo(id="my-model")]

    def chat(self, messages, model, temperature=0.2, max_tokens=2048):
        yield "..."  # stream text chunks

register_driver("my_api", "My API", "What it is", cls=MyProvider)
```

Restart: the type appears in **Settings → Add provider**. Endpoints that speak the OpenAI shape need
no code — add them as a `openai_compat` custom provider.

**A new file format:**

```python
# backend/app/extractors/rtf.py
from app.extractors.base import ExtractedPage
from app.extractors.registration import register_extractor

def extract_rtf(path: str) -> list[ExtractedPage]:
    return [ExtractedPage(number=1, text=open(path).read())]

register_extractor(["rtf"], "Rich Text", extract_rtf)
```

**A new game type / role:** use **Settings → Game types**, no restart needed.

Other extension points: `services/chunking.py` (splitting), `services/search.py` (ranking),
`services/rag.py` (prompting), or add a new router in `app/api/`.

## Troubleshooting

- **“Ollama unreachable” from Docker.** Use `http://host.docker.internal:11434`, keep
  `extra_hosts: host.docker.internal:host-gateway` (already in the compose file), and make sure
  Ollama listens on all interfaces (`OLLAMA_HOST=0.0.0.0`).
- **PDF indexed 0 pages.** It is a scan without a text layer; OCR it first.
- **Changed the embedding model and search feels wrong.** Settings → Search & answers →
  *Re-embed everything*.
- **Permission denied on a bind mount.** The container runs as UID 1000; `chown -R 1000:1000` the
  host folder, or use the named volume (recommended).

## License

MIT — see [LICENSE](LICENSE). Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
