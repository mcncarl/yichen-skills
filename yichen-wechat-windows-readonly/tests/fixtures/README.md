# Synthetic Fixtures Only

`build_synthetic_vault.py` creates a small fictional Vault under a caller-supplied output directory. The generated SQLite files are test artifacts and must not be committed.

The fixture intentionally includes:

- two contacts with the same display name for ambiguity tests;
- one direct session and one group session;
- plain text messages for history, search, and statistics;
- one non-text message whose body must never be returned;
- deterministic timestamps and fictional identifiers.

Tests create additional temporary variants for WAL, corruption, invalid paths, and concurrent mutation.
