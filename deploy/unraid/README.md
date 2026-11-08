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
