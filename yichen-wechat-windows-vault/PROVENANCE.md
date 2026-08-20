# Provenance

## Relationship to the Mac Skill

This Skill follows the existing `yichen-wechat-local-vault` user-facing concepts: local private vault, sessions, contacts, members, history, search, statistics, export, Favorites, Moments, and digest-source generation. That same-repository Skill was used as the functional and interface reference.

The following Windows components were implemented independently for this contribution:

- exact Windows PE fingerprint and prologue validation;
- finite Frida attachment to one explicitly selected Weixin process;
- derived-key candidate handling and page-HMAC verification;
- Windows DPAPI key storage;
- snapshot-based incremental decryption;
- Windows WeChat 4.x contact, session, message-shard, Favorites, Moments, and resource-index adapters;
- synthetic fixtures and automated tests.

## Excluded sources

No source code, implementation details, binary, package, fork, mirror, or generated output from wx-cli, wxcli, jackwener, or related projects was consulted, copied, adapted, or invoked. The implementation does not detect or import those packages at runtime.

No code from the previously closed Windows v0.1/v0.3 contribution was reused. Existing private vault tooling was used only as a black-box source of schema availability and query-count comparisons; its source was not used to implement this Skill.

## Independent compatibility derivation

The supported Windows profile was derived from the user's installed `Weixin.dll` by:

1. hashing the complete DLL;
2. reading PE exception-function boundaries;
3. locating an embedded OpenSSL source assertion reference for `crypto/evp/p5_crpt2.c`;
4. identifying the adjacent x64 function by the documented `PKCS5_PBKDF2_HMAC` argument and loop structure;
5. recording and checking the exact function prologue;
6. accepting captured results only when the SQLCipher page HMAC validates against an explicit local database.

Official OpenSSL, SQLCipher, and Frida documentation were used as protocol and API references. No third-party implementation was copied into the repository.
