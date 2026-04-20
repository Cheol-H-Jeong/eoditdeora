# Linux Installer

Primary artifact: `Eoditdeora.AppImage` — a single executable that
requires no root and runs on Ubuntu 22.04 / 24.04, Fedora 39+, and
similar. Secondary artifacts (`.deb`, `.rpm`) are published for users
who want package-manager integration.

Build locally from the repo root:

```bash
pnpm install
pnpm --filter eoditdeora-ui build
cd apps/shell && cargo tauri build
```

The resulting files appear under
`apps/shell/target/release/bundle/{appimage,deb,rpm}/`.

## Air-gapped / offline installs

For 공무원 PCs with no internet access:

1. On a build machine with network: run the model download script once
   (`python scripts/download-models.py`) so the GGUFs land in
   `~/.local/share/eoditdeora/models/`.
2. Ship the AppImage AND the models directory on the same USB/CD.
3. On the target machine, copy the models into the same path or set
   `EODITDEORA_HOME` to a directory that contains a `models/` folder.

The app never calls out to the network unless the model directory is
empty AND `scripts/download-models.py` is explicitly run.
