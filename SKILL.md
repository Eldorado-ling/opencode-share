---
name: opencode-share
description: Extract, clean, and summarize OpenCode shared session links from opncd.ai/share, opencode.ai/s, or saved OpenCode share HTML. Use when the user provides an OpenCode share session URL and wants the meaningful conversation, user inputs, assistant outputs, session metadata, task handoff context, or a concise summary without tool-call noise, internal state, paths, or reasoning artifacts.
---

# OpenCode Share

## Workflow

Use the bundled parser first. Do not manually inspect the page unless the parser fails or the user needs debugging details.

```powershell
python "$env:USERPROFILE\.codex\skills\opencode-share\scripts\extract_opencode_share.py" "https://opncd.ai/share/SHARE_ID" --out ".\opencode-clean.md"
```

The parser accepts `https://opencode.ai/s/SHARE_ID` and automatically rewrites it to the share endpoint before fetching.

For a saved HTML file:

```powershell
python "$env:USERPROFILE\.codex\skills\opencode-share\scripts\extract_opencode_share.py" ".\share.html" --out ".\opencode-clean.md"
```

The script outputs:

- A clean Markdown transcript containing only user visible text and assistant visible text.
- Optional JSON with `--json-out path.json`.
- Session metadata, transcript counts, and typed failure messages.

## Summarizing

After extraction, read the generated Markdown and produce the user-requested artifact:

- For "summarize": provide a concise Chinese summary of the task, decisions, results, and any unresolved next steps.
- For handoff or continuation requests: identify the latest user intent, current state, files or URLs mentioned, and the next concrete action.
- For requests to show only effective messages: return or reference the clean Markdown transcript.

Do not include assistant reasoning parts, tool outputs, token/cost data, hidden IDs, model metadata, or large raw HTML fragments unless the user explicitly asks for forensic details.

## Notes

- OpenCode share pages often embed session data in one large script line with `$R[...]` references. The parser reconstructs message order, role, and visible `type:"text"` parts.
- Some shared pages expose only public share data. If requested content was never included in the share HTML or requires authentication, state that limitation clearly.
- If the URL fetch fails in the browser tool, use the script anyway; it performs a direct HTTP request.
- Treat exit code 2 as fetch/read failure, 3 as missing share data, and 4 as empty visible transcript.
