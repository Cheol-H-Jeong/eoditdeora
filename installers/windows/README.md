# Windows Installer

Primary artifact: `Eoditdeora-0.1.0-x64.msi` — built by `cargo tauri
build` on `windows-latest` in CI. The MSI uses the WiX toolset
configuration that Tauri generates automatically.

Build locally (Windows host):

```powershell
pnpm install
pnpm --filter eoditdeora-ui build
cd apps/shell
cargo tauri build
```

The MSI appears under `apps\shell\target\release\bundle\msi\`.

## Defender / corporate AV

Add `%LOCALAPPDATA%\eoditdeora\` to Defender's exclusion list. The
indexer can produce high file-system fanout during initial scans, which
AV real-time scanners may otherwise throttle to a crawl.

## Air-gapped installs

Identical approach to Linux: ship models alongside the MSI and drop
them into `%LOCALAPPDATA%\eoditdeora\models\` before first launch. The
app will not attempt any outbound network request on its own.
