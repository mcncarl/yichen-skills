# Third-party notices

No third-party source code or binary is vendored in this Skill. Python packages are installed from PyPI at setup time.

| Package | Pinned version | Purpose | License | Upstream |
|---|---:|---|---|---|
| `cryptography` | 50.0.0 | AES-256-CBC page encryption primitives used by the decoder | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| `zstandard` | 0.25.0 | Optional decoding of Zstandard-compressed Weixin message fields | BSD-3-Clause | https://github.com/indygreg/python-zstandard |
| `cffi` | 2.1.1 | Transitive dependency of `cryptography` | MIT-0 | https://github.com/python-cffi/cffi |
| `pycparser` | 3.0 | Transitive dependency of `cffi` | BSD-3-Clause | https://github.com/eliben/pycparser |

The package metadata and full license texts are available from each upstream distribution. The repository's own license continues to govern this Skill's source code and usage.

Public technical documentation and source repositories listed in `README.md` were used as references. Referencing those materials does not bundle their code or change this repository's license.
