# Python Runtime Package Profiles

PyStudio keeps the default Python runtime small and downloads optional runtime
repositories only when a user asks for that capability.

## Profiles

| Profile | Purpose | Packages |
| --- | --- | --- |
| `python` | Baseline CPython and pip. | `python python-pip` |
| `python-build` | Native extension build tools for `pip install` fallback builds. | `make cmake ninja pkg-config binutils ndk-sysroot libllvm autoconf automake libtool m4 patchelf rust python-cmake` |
| `python-science` | Numeric and scientific computing foundation. | `python-numpy python-scipy libopenblas fftw` |
| `python-data` | Common data and runtime utility modules available in the source tree. | `python-apsw python-brotli python-greenlet python-msgpack python-psutil python-pyppmd` |
| `python-image` | Image processing libraries and Python bindings. | `python-pillow libjpeg-turbo libpng libtiff libwebp littlecms openjpeg python-skia-pathops` |
| `python-viz` | Plotting and text/font dependencies. | `matplotlib python-contourpy freetype fontconfig qhull` |
| `python-xml-html` | XML, HTML, and parser tooling. | `python-lxml libxml2 libxslt html-xml-utils html2text xmlstarlet xmlsec tree-sitter-html tree-sitter-xml` |
| `python-crypto-network` | Crypto and protocol libraries. | `python-cryptography python-bcrypt python-pycryptodomex openssl libffi libsodium libgcrypt libnghttp2 libnghttp3 libmicrohttpd libxmlrpc` |
| `python-gui-tk` | Tkinter runtime support and Tcl/Tk/X11 dependencies. | `tk tcl tcllib xorgproto libx11 libxft libxext python-xlib` |

Every optional profile also includes `python python-pip` so each generated apt
repository is installable on top of a minimal bootstrap without assuming another
PyStudio package repository has already been unpacked.

## Notes

- `python-tkinter` is a Python subpackage produced by building `python`, not a
  standalone package directory. The `python-gui-tk` profile builds `python`
  together with `tk` and `tcl`, so the apt repository should contain the
  `python-tkinter` `.deb` plus the runtime libraries it needs.
- Packages such as `pandas`, `beautifulsoup4`, and `requests` are not currently
  present as Termux package directories in the two source adapters. They should
  remain `pip install` targets. The split profiles provide the native runtime
  and build dependencies those pip installs commonly need.
- Heavy packages such as `python-torch`, `flang`, `imagemagick`, `graphviz`,
  `pycairo`, and `libcairo` are intentionally excluded from the default full
  Python matrix. They should become separate opt-in profiles after the smaller
  matrix is stable.

## Build

Build every Python profile for the selected source and all four architectures:

```powershell
# Actions -> Build PyStudio Toolchain Matrix
profile: all-python
source: primary
architectures: aarch64,arm,i686,x86_64
publish_release: true
```

This resolves to 36 build jobs:

```text
9 Python profiles x 1 selected source x 4 architectures
```

During each job, the selected source tree is still allowed to borrow missing
package directories from the configured fallback sources. The release contains
one installable repository result, not multiple competing source results.

For smoke tests, restrict the matrix:

```powershell
profile: python-gui-tk
source: primary
architectures: aarch64
publish_release: false
```
