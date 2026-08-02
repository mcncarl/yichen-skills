# yichen-wecom-operations

Operate owner-authorized WeCom documents, todos, meetings, and schedules through the official [`@wecom/cli`](https://github.com/WecomTeam/wecom-cli), without controlling the WeCom desktop app or sending messages.

## Capabilities

- Create normal documents and Markdown-based smart documents.
- Read or overwrite documents only after target and permission checks.
- Create, inspect, update, and delete todos with confirmation gates.
- Manage meetings and schedules when the current enterprise grants those categories.
- Preflight every write; destructive or replacement operations require explicit confirmation.
- Store internal IDs and receipts only in private local state.

## Install

Install and configure the official CLI first:

```bash
npm install -g @wecom/cli
wecom-cli init
```

Run `wecom-cli init` only for a new setup. If `~/.config/wecom/` already contains the encrypted configuration files, keep the existing configuration instead of overwriting it.

Install this Skill from the collection:

```bash
npx skills add mcncarl/yichen-skills --skill yichen-wecom-operations
```

Then check the runtime:

```bash
python3 "$HOME/.agents/skills/yichen-wecom-operations/scripts/doctor.py"
python3 "$HOME/.agents/skills/yichen-wecom-operations/scripts/doctor.py" --category doc
```

## Local-image boundary

The official CLI can create text documents and use already-hosted images. The bundled `create_smartpage.py` can also rewrite local Markdown image paths, but uploading those local images requires a separately supplied executable that exposes `doc +doc_upload_image`:

```bash
export WECOM_UPLOAD_HELPER=/absolute/path/to/wecom-cli-with-doc-upload-image
```

That helper is a local extension and is not distributed in this repository. Without it, use Markdown containing no local images, or replace images with authorized remote URLs before execution.

## Safety and privacy

- Never operates the WeCom desktop UI and never calls the message category.
- Never reads or prints encrypted credential contents under `~/.config/wecom/`.
- Write operations require a current-task user instruction; cancellation, deletion, and full-document overwrite require exact-target reconfirmation.
- Do not commit Bot IDs, secrets, user IDs, document/meeting/todo IDs, authorization URLs, receipts, source documents, or customer data.
- Category availability is tenant-specific and must be checked dynamically.

## License and upstream

Original files in this directory follow the repository's [Personal Learning and Non-Commercial Use License](../LICENSE). The external [`WeComTeam/wecom-cli`](https://github.com/WecomTeam/wecom-cli) runtime is maintained separately by WeComTeam under its own MIT License; no upstream CLI source or binary is vendored here.
