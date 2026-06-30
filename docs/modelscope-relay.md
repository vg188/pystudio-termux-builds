# ModelScope Package Repository Relay

`scripts/local/modelscope_release_relay.py` mirrors PyStudio package
repositories to a public ModelScope dataset.

GitHub Releases remain the authority. The main release stores flat
`Packages.xz` indexes and metadata; package pool releases store `.deb` files.
The relay downloads both and uploads the matching ModelScope layout:

```text
repo/<owner>/<repo>/<release-tag>/<artifact-prefix>/<arch>/
  ARTIFACT-apt-repo-v1-ARCH-rN-Packages.xz
pool/<owner>/<repo>/<pool-release-tag>/<all-or-arch>/
  package_version_ARCH.deb
```

Gitee is not a package mirror. It only stores the lightweight
`runtime-packages.json` manifest.

## Setup

Install the ModelScope CLI:

```powershell
python -m pip install -U modelscope
```

Set a user environment variable named `modelscope_yourba`. The scripts also
check `MODELSCOPE_YOURBA` and `MODELSCOPE_TOKEN`.

```powershell
$env:modelscope_yourba="..."
```

Create or reuse the public dataset:

```powershell
modelscope create yourba/pystudio-termux-builds `
  --repo_type dataset `
  --visibility public `
  --exist_ok `
  --token $env:modelscope_yourba
```

## Usage

Dry run:

```powershell
python scripts/local/modelscope_release_relay.py --dry-run --max-repositories 2
```

Mirror every package repository referenced by `runtime-packages.json`:

```powershell
python scripts/local/modelscope_release_relay.py
```

Mirror one repository by ID or URL substring:

```powershell
python scripts/local/modelscope_release_relay.py --include python-lsp
```

The script shows download progress and upload speed. It skips remote files that
already exist unless `--force-upload` is set.

## Cleanup

The old flat mirror used `assets/**` and `runtime-packages-modelscope.json`.
Those are no longer used by schema 5. Use:

```powershell
python scripts/local/modelscope_cleanup_unused.py --dry-run
python scripts/local/modelscope_cleanup_unused.py
```

If ModelScope returns failed deletions, the script exits non-zero and prints the
first failed paths. In that case, delete those files from the ModelScope web UI
or rerun with a token that has dataset delete permission.

## App URLs

The schema 5 manifest already contains ModelScope full-repo mirrors:

```json
{
  "id": "modelscope",
  "kind": "flat-package-repo",
  "baseUrl": "https://modelscope.cn/datasets/yourba/pystudio-termux-builds/resolve/master/repo/...",
  "indexUrl": "https://modelscope.cn/datasets/yourba/pystudio-termux-builds/resolve/master/repo/.../ARTIFACT-apt-repo-v1-ARCH-rN-Packages.xz",
  "priority": 10,
  "region": "CN"
}
```

The app downloads `Packages.xz` from `indexUrl`, then resolves `.deb` files from
the matching `packagePools[]` mirror. Joining `baseUrl` with `Filename` is only a
fallback for legacy flat releases.
