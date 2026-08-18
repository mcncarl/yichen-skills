const fs = require("fs");
const path = require("path");

async function main() {
  if (process.argv.length !== 4) {
    throw new Error("usage: node decode_silk.cjs INPUT.silk OUTPUT.pcm");
  }
  const runtime = path.join(
    process.env.LOCALAPPDATA,
    "wechat-windows-vault",
    "node-runtime",
    "node_modules",
    "silk-wasm",
    "lib",
    "index.cjs"
  );
  const { decode } = require(runtime);
  const input = fs.readFileSync(process.argv[2]);
  const result = await decode(input, 24000);
  fs.writeFileSync(process.argv[3], result.data);
  process.stdout.write(JSON.stringify({ duration_ms: result.duration }));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
