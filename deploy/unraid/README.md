# Ruleshelf on Unraid (container template)

Import `ruleshelf.xml` through **Docker → Add Container → Template** (or copy it
to `/boot/config/plugins/dockerMan/templates-user/`), then adjust the port and
host path.

Create and update the container from the Unraid Docker page. Containers started
with a bare `docker run` appear as **3rd Party** because dockerMan identifies its
own containers by the `net.unraid.docker.managed=dockerman` label (plus the
template in `templates-user`). If you recreate one from the command line, pass
that label and the icon/WebUI labels shown in the template; otherwise use the
template's **Edit**/**Apply** action.

Recommended layout on the array:

```
/mnt/user/Data/ruleshelf/
└── data/          # mounted to /data: ruleshelf.db, config.json, files/, thumbnails/
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
docker exec Ollama ollama pull qwen2.5:14b-instruct-q4_K_M   # quality, ~60s/answer
docker exec Ollama ollama pull llama3.1:8b-instruct-q4_K_M   # faster, ~30s/answer
```

Then in Ruleshelf **Settings → AI providers → Ollama**, set the chat model to
`qwen2.5:14b-instruct-q4_K_M` (or the 8B for speed) and the embedding model to
`nomic-embed-text`.
