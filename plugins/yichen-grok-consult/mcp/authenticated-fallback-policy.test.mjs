import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  AUTHENTICATED_FALLBACK_ERROR,
  requireAuthenticatedFallbackAuthorization,
} from "./authenticated-fallback-policy.mjs";

test("authenticated fallback is denied unless the flag is exactly true", () => {
  for (const args of [undefined, {}, { allow_authenticated_fallback: false }, { allow_authenticated_fallback: 1 }, { allow_authenticated_fallback: "true" }]) {
    assert.throws(
      () => requireAuthenticatedFallbackAuthorization(args),
      (error) => error instanceof Error && error.message === AUTHENTICATED_FALLBACK_ERROR,
    );
  }
  assert.doesNotThrow(() =>
    requireAuthenticatedFallbackAuthorization({ allow_authenticated_fallback: true }),
  );
});

test("both authenticated readers and the fallback chain enforce the gate", async () => {
  const source = await readFile(new URL("./server.mjs", import.meta.url), "utf8");
  const openCliBody = source.slice(
    source.indexOf("async function callOpenCliSearch"),
    source.indexOf("async function callFxTwitterSearch"),
  );
  const xreachBody = source.slice(
    source.indexOf("async function callXreachSearch"),
    source.indexOf("async function callNativeSearch"),
  );
  const fallbackChain = source.slice(
    source.indexOf('attempts.push(routeAttempt("fxtwitter-public", error));'),
    source.indexOf('attempts.push(routeAttempt("opencli", error));'),
  );

  assert.match(openCliBody, /requireAuthenticatedFallbackAuthorization\(args\)/);
  assert.match(xreachBody, /requireAuthenticatedFallbackAuthorization\(args\)/);
  assert.match(fallbackChain, /args\.allow_authenticated_fallback !== true/);
  assert.ok(
    fallbackChain.indexOf("allow_authenticated_fallback") <
      fallbackChain.indexOf("await callOpenCliSearch"),
  );
});

test("tool schema exposes a fail-closed boolean flag", async () => {
  const source = await readFile(new URL("./server.mjs", import.meta.url), "utf8");
  assert.match(source, /allow_authenticated_fallback:\s*\{\s*type:\s*"boolean",\s*default:\s*false/);
  assert.match(source, /additionalProperties:\s*false/);
});
