"""Synthetic regressions for extract_keys.py Frida symbol resolution and arm64 +4 fallback.

No real WeChat binary, process, key, or database is accessed.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import extract_keys

HAS_NODE = shutil.which("node") is not None


HARNESS_JS = r"""
const vm = require('vm');

const scenario = JSON.parse(process.argv[1]);
const scriptSource = process.argv[2];

function makePtr(addr, memMap) {
  return {
    _addr: addr,
    isNull: () => addr === 0,
    add: (n) => makePtr(addr + n, memMap),
    toInt32: () => addr | 0,
    readU32: () => {
      if (!(addr in memMap)) throw new Error('unreadable address ' + addr);
      return memMap[addr];
    },
    readByteArray: (len) => {
      if (!(addr in memMap)) throw new Error('unreadable bytes ' + addr);
      return memMap[addr].slice(0, len);
    },
  };
}

const memMap = scenario.mem || {};
const messages = [];
const attached = [];
let scheduled = 0;

const Module = {};
if (scenario.globalApi === 'get') {
  Module.getGlobalExportByName = (name) => {
    if (scenario.globalThrows) throw new Error('lookup failed');
    return name === 'CCKeyDerivationPBKDF' && scenario.globalAddr != null
      ? makePtr(scenario.globalAddr, memMap)
      : null;
  };
} else if (scenario.globalApi === 'find') {
  Module.findGlobalExportByName = (name) => {
    return name === 'CCKeyDerivationPBKDF' && scenario.globalAddr != null
      ? makePtr(scenario.globalAddr, memMap)
      : null;
  };
}

const Process = {
  arch: scenario.arch || 'arm64',
  enumerateModules: () => (scenario.modules || []).map((m) => ({
    name: m.name,
    enumerateExports: () => (m.exports || []).map((e) => ({
      name: e.name,
      address: makePtr(e.addr, memMap),
    })),
  })),
};

const Instruction = {
  parse: (ptr) => {
    if ((scenario.undecodable || []).includes(ptr._addr)) {
      throw new Error('cannot decode instruction at ' + ptr._addr);
    }
    return { address: ptr };
  },
};

const Interceptor = {
  attach: (ptr, callbacks) => {
    if ((scenario.attachFails || []).includes(ptr._addr)) {
      throw new Error('unable to intercept function at 0x' + ptr._addr.toString(16));
    }
    attached.push({ addr: ptr._addr, hasEnter: typeof callbacks.onEnter === 'function', hasLeave: typeof callbacks.onLeave === 'function' });
  },
};

const sandbox = {
  Module,
  Process,
  Instruction,
  Interceptor,
  File: function() { return { write() {}, flush() {}, close() {} }; },
  send: (msg) => messages.push(msg),
  setTimeout: () => { scheduled += 1; },
  Uint8Array,
  JSON,
  Date,
};

let uncaught = null;
try {
  vm.runInNewContext(scriptSource, sandbox);
} catch (err) {
  uncaught = String(err && err.message ? err.message : err);
}

console.log(JSON.stringify({ attached, messages, scheduled, uncaught }));
"""


def run_frida_js(scenario: dict) -> dict:
    js_code = (
        extract_keys.FRIDA_JS
        .replace("___LOG_PATH___", "/tmp/synthetic-unused.log")
        .replace("___TARGET_SALTS___", "[]")
    )
    proc = subprocess.run(
        ["node", "-e", HARNESS_JS, json.dumps(scenario), js_code],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


class ExtractKeysFridaJsTests(unittest.TestCase):
    def test_frida_js_contains_global_export_and_arm64_fallback(self):
        self.assertIn("Module.getGlobalExportByName || Module.findGlobalExportByName", extract_keys.FRIDA_JS)
        self.assertIn("resolveGlobalExport('CCKeyDerivationPBKDF')", extract_keys.FRIDA_JS)
        self.assertIn("Process.arch !== 'arm64'", extract_keys.FRIDA_JS)
        self.assertIn("Instruction.parse", extract_keys.FRIDA_JS)

    @unittest.skipUnless(HAS_NODE, "node is required to execute mocked FRIDA_JS harness")
    def test_resolves_via_frida17_global_export_when_module_exports_empty(self):
        result = run_frida_js({
            "globalApi": "get",
            "globalAddr": 0x1000,
            "modules": [{"name": "libcommonCrypto.dylib", "exports": []}],
        })
        self.assertIsNone(result["uncaught"])
        self.assertEqual([item["addr"] for item in result["attached"]], [0x1000])
        statuses = [m["msg"] for m in result["messages"] if m.get("type") == "status"]
        self.assertIn("Hook installed on global export table!CCKeyDerivationPBKDF", statuses)

    @unittest.skipUnless(HAS_NODE, "node is required to execute mocked FRIDA_JS harness")
    def test_resolves_via_frida16_find_global_export(self):
        result = run_frida_js({
            "globalApi": "find",
            "globalAddr": 0x2000,
            "modules": [],
        })
        self.assertIsNone(result["uncaught"])
        self.assertEqual([item["addr"] for item in result["attached"]], [0x2000])

    @unittest.skipUnless(HAS_NODE, "node is required to execute mocked FRIDA_JS harness")
    def test_falls_back_to_module_scan_when_global_lookup_fails(self):
        result = run_frida_js({
            "globalApi": "get",
            "globalThrows": True,
            "modules": [{"name": "libcommonCrypto.dylib", "exports": [{"name": "CCKeyDerivationPBKDF", "addr": 0x3000}]}],
        })
        self.assertIsNone(result["uncaught"])
        self.assertEqual([item["addr"] for item in result["attached"]], [0x3000])
        statuses = [m["msg"] for m in result["messages"] if m.get("type") == "status"]
        self.assertIn("Hook installed on libcommonCrypto.dylib!CCKeyDerivationPBKDF", statuses)

    @unittest.skipUnless(HAS_NODE, "node is required to execute mocked FRIDA_JS harness")
    def test_arm64_undecodable_pacibsppc_prologue_hooks_at_plus_4(self):
        result = run_frida_js({
            "arch": "arm64",
            "globalApi": "get",
            "globalAddr": 0x4000,
            "mem": {0x4000: 0xDAC1A7FE},  # pacibsppc
            "attachFails": [0x4000],
            "undecodable": [0x4000],
        })
        self.assertIsNone(result["uncaught"])
        self.assertEqual([item["addr"] for item in result["attached"]], [0x4004])
        statuses = [m["msg"] for m in result["messages"] if m.get("type") == "status"]
        self.assertTrue(any("0xdac1a7fe" in msg and "+4" in msg for msg in statuses))
        self.assertIn("Hook installed on global export table!CCKeyDerivationPBKDF (+4)", statuses)

    @unittest.skipUnless(HAS_NODE, "node is required to execute mocked FRIDA_JS harness")
    def test_decodable_entry_attach_error_does_not_offset_to_plus_4(self):
        result = run_frida_js({
            "arch": "arm64",
            "globalApi": "get",
            "globalAddr": 0x5000,
            "mem": {0x5000: 0xA9BB7BFD},
            "attachFails": [0x5000],
            "undecodable": [],
        })
        self.assertEqual(result["attached"], [])
        self.assertIsNotNone(result["uncaught"])
        self.assertIn("unable to intercept", result["uncaught"])

    @unittest.skipUnless(HAS_NODE, "node is required to execute mocked FRIDA_JS harness")
    def test_non_arm64_does_not_offset_to_plus_4(self):
        result = run_frida_js({
            "arch": "x64",
            "globalApi": "get",
            "globalAddr": 0x6000,
            "mem": {0x6000: 0xDAC1A7FE},
            "attachFails": [0x6000],
            "undecodable": [0x6000],
        })
        self.assertEqual(result["attached"], [])
        self.assertIsNotNone(result["uncaught"])


if __name__ == "__main__":
    unittest.main()
