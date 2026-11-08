# Ruleshelf on Unraid (container template)

Import `ruleshelf.xml` through **Docker → Add Container → Template** (or copy it
to `/boot/config/plugins/dockerMan/templates-user/`), then adjust the port and
host path.

Recommended layout on the array:

```
/mnt/user/Data/ruleshelf/
└── data/          # mounted to /data: ruleshelf.db + files/
```

Host port `8787` is used in the template. Check it is free first:

```bash
ss -ltn | grep ':8787 ' || echo "8787 is free"
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 8787 || true
```

The template sets `PUID=99` and `PGID=100` (Unraid's `nobody:users`) so files are
readable from the array over SMB. The container chowns `/data` on start and then
drops privileges.

## Local AI on the same server

Ollama is a separate container, models stored on the array:

```
/mnt/user/Data/ollama/
└── models/          # pulled models (about 5-10 GB)
```

Template: [`ollama.xml`](ollama.xml). It maps port `11434` and mounts
`/mnt/user/Data/ollama` to `/root/.ollama`. Pull the models once:

```bash
docker exec Ollama ollama pull nomic-embed-text
docker exec Ollama ollama pull llama3.1:8b-instruct-q4_K_M
```

Then in Ruleshelf **Settings → AI providers → Ollama**, set the chat model to
`llama3.1:8b-instruct-q4_K_M` and the embedding model to `nomic-embed-text`.
