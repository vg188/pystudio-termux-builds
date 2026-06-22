# Gitee Local Relay

`scripts/local/gitee_release_relay.py` mirrors runtime package assets through a
developer PC instead of a GitHub-hosted runner.

Why this exists:

- GitHub-hosted runners often have slow or unstable uploads to Gitee for large
  release assets.
- A local PC can keep a persistent cache and retry only failed files.
- The app-facing artifact format stays unchanged: normal `.tar.gz` and
  `SHA256SUMS-*.txt` files are uploaded to a Gitee release, and
  `runtime-packages.json` is rewritten to Gitee URLs.

## Usage

Set tokens in the current terminal. Do not commit them.

```powershell
$env:GITEE_TOKEN="..."
$env:GITHUB_TOKEN=$env:git_token_vg188
python scripts/local/gitee_release_relay.py `
  --manifest runtime-packages.json `
  --gitee-owner yourba `
  --gitee-repo pystudio-termux-builds `
  --gitee-branch main
```

For a smoke test, limit the upload:

```powershell
python scripts/local/gitee_release_relay.py --max-assets 2
```

To mirror only one toolchain family:

```powershell
python scripts/local/gitee_release_relay.py --include "pystudio-python-toolchain"
```

The default cache is `work/gitee-relay`, which is ignored by git.

Transfer progress is enabled by default:

- Downloads show percent, transferred size, total size when known, current
  speed, and elapsed time.
- Uploads use curl's progress meter, then print final upload size, total time,
  and average upload speed.
- `--progress-interval` controls the download progress refresh interval in
  seconds. The default is `0.5`.
- Gitee HTTP 400 responses stop immediately instead of retrying the same large
  upload. The response body is printed and saved under
  `work/gitee-relay/upload-responses/`.

## Behavior

- Downloads are cached locally.
- Partial downloads are resumed when the server supports HTTP range requests.
- Existing local downloads are skipped unless `--force-download` is set.
- Existing Gitee release assets are skipped unless `--force-upload` is set.
- The Gitee repository file `runtime-packages.json` is updated only after the
  assets are uploaded.

## Notes

The script intentionally does not split `.tar.gz` files by default. Splitting
would improve upload recovery, but it would also require app-side reassembly or
a second manifest layer. Keep the first local relay compatible with the current
app downloader.
