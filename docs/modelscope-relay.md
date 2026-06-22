# ModelScope Runtime Package Relay

`scripts/local/modelscope_release_relay.py` mirrors selected runtime package
assets to a public ModelScope dataset repository.

This is the preferred free mainland-download mirror after Gitee's release
attachment limits proved too small for PyStudio runtime packages.

## Setup

Install the ModelScope CLI:

```powershell
python -m pip install -U modelscope
```

Set a user environment variable named `modelscope_yourba`. The script also
checks `MODELSCOPE_YOURBA` and `MODELSCOPE_TOKEN`.

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
python scripts/local/modelscope_release_relay.py --dry-run --max-assets 2
```

Upload all app-facing runtime package archives and checksum files:

```powershell
python scripts/local/modelscope_release_relay.py
```

If the GitHub assets are already cached under `work/gitee-relay/assets`, skip
the download step:

```powershell
python scripts/local/modelscope_release_relay.py --no-download
```

By default, the script mirrors only:

- `*-repo-*.tar.gz`
- `SHA256SUMS-*.txt`

It intentionally skips `*-debs-*.tar.gz`, which is useful for debugging but not
needed by the app's normal runtime package installer.

To mirror every archive, including raw `.deb` bundles, override the filter:

```powershell
python scripts/local/modelscope_release_relay.py `
  --include "(-repo-[^/]+\.tar\.gz|-debs-[^/]+\.tar\.gz|SHA256SUMS-[^/]+\.txt)$"
```

## Output

The generated manifest is written locally to:

```text
work/gitee-relay/manifest/runtime-packages-modelscope.json
```

It is also uploaded to the ModelScope dataset root. The public URL uses this
shape:

```text
https://modelscope.cn/api/v1/datasets/yourba/pystudio-termux-builds/repo?Revision=master&FilePath=runtime-packages-modelscope.json
```

Current public dataset:

```text
https://www.modelscope.cn/datasets/yourba/pystudio-termux-builds
```

The first full relay uploaded 47 app-facing files, about 3.04 GiB total, then
refreshed `runtime-packages-modelscope.json` with 47 ModelScope package URLs.
The debug-only `*-debs-*.tar.gz` URLs remain pointed at GitHub.

## Verification

After upload, verify that public download works:

```powershell
$url="https://modelscope.cn/api/v1/datasets/yourba/pystudio-termux-builds/repo?Revision=master&FilePath=runtime-packages-modelscope.json"
curl.exe -L -I $url
curl.exe -L -r 0-1023 -o NUL $url
```

ModelScope may return either `206 Partial Content` or `200 OK` depending on the
CDN path, but the public manifest must be readable without authentication.
