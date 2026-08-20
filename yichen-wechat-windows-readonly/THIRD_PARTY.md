# Third-Party Dependencies and Licenses

## Runtime dependencies

None. The adapter and its tests use only the Python 3.11+ standard library.

No package manager lockfile is needed because there are no installable third-party packages to resolve or lock.

## CI actions

The workflow uses the same official, commit-pinned actions already present at the clean baseline:

| Action | Integrity pin | License | Source |
| --- | --- | --- | --- |
| `actions/checkout` v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` | MIT | Official `actions/checkout` GitHub repository |
| `actions/setup-python` v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` | MIT | Official `actions/setup-python` GitHub repository |

No floating action tag is used.

## Bundled third-party material

None. No external source code, binary, database, fixture, media, or generated artifact is bundled.

## Repository license

This contribution is covered by the repository's root `LICENSE`. Python itself is a user-supplied runtime and is not redistributed by this contribution. The two CI actions run remotely and are not bundled.
