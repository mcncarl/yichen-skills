# Third-Party Notices

Runtime dependencies are pinned in `requirements.txt` and installed into an isolated local environment.

| Dependency | Version | Purpose | License / source |
|---|---:|---|---|
| Frida Python bindings | 17.15.4 | Finite local process instrumentation | wxWindows Library Licence 3.1; https://github.com/frida/frida |
| PyCryptodome | 3.23.0 | AES-256-CBC operations | BSD / public-domain components; https://github.com/Legrandin/pycryptodome |
| python-zstandard | 0.23.0 | WeChat compressed message decoding | BSD-3-Clause; https://github.com/indygreg/python-zstandard |
| pytest | 8.4.1 | Development tests only | MIT; https://github.com/pytest-dev/pytest |

Reference-only specifications and source navigation:

- SQLCipher official source and verification utility (BSD-3-Clause) were consulted for page layout, HMAC salt masking, key derivation, and little-endian page numbering. No SQLCipher source is vendored.
- OpenSSL 1.1.1 source was consulted to identify the public `PKCS5_PBKDF2_HMAC` function structure in a local binary. No OpenSSL source is vendored.
- The same-repository Mac Skill was consulted only for the product interface and functional vocabulary under this repository's license.
