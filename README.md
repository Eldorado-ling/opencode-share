# OpenCode Share

Extract the meaningful transcript from an OpenCode shared session link.

OpenCode share pages can contain a lot of runtime data: tool calls, reasoning
parts, token counts, status objects, model metadata, and internal references.
This skill keeps the parts people usually need for handoff and review:

- user-visible prompts
- assistant-visible text responses
- message order
- session metadata
- clean Markdown output
- optional JSON output

## Use as a Codex skill

Copy this folder into your Codex skills directory:

```powershell
$env:USERPROFILE\.codex\skills\opencode-share
```

Then ask Codex to analyze an OpenCode share URL, for example:

```text
Analyze this OpenCode share session and summarize the effective conversation:
https://opncd.ai/share/SHARE_ID
```

## Use the parser directly

Requirements: Python 3.10 or newer. No third-party packages are required.

From a URL:

```powershell
python .\scripts\extract_opencode_share.py "https://opncd.ai/share/SHARE_ID" --out clean.md
```

The parser also accepts `https://opencode.ai/s/SHARE_ID` and rewrites it to
the `opncd.ai/share/SHARE_ID` format before fetching.

From a saved HTML file:

```powershell
python .\scripts\extract_opencode_share.py ".\share.html" --out clean.md
```

With JSON output:

```powershell
python .\scripts\extract_opencode_share.py "https://opncd.ai/share/SHARE_ID" --out clean.md --json-out clean.json
```

## Unicode handling

Share pages sometimes contain UTF-8 bytes that were decoded as Latin-1
("mojibake"). The parser repairs that on a best-effort basis, and only when
the whole string can be converted back without losing characters. Text that
mixes mojibake with characters outside Latin-1 (emoji, other scripts,
combining marks) is left exactly as supplied instead of being repaired
partially, because a partial repair would silently delete the characters it
cannot re-encode.

## Output

The Markdown output contains:

```text
# OpenCode Share Session - Clean Transcript

## Metadata

Source: ...
Messages: ...
Share ID: ...
Title: ...
Model: ...
Tokens: ...

## Transcript

## 1. User

...

## 2. Assistant

...
```

The JSON output contains:

```json
{
  "metadata": {
    "source": "...",
    "share_id": "...",
    "title": "...",
    "model": {
      "id": "..."
    }
  },
  "message_count": 2,
  "messages": [
    {
      "id": "msg_...",
      "role": "user",
      "text": "..."
    }
  ]
}
```

## Exit codes

- `0`: extraction succeeded
- `2`: URL fetch or local file read failed
- `3`: no OpenCode share data was found
- `4`: share data existed, but no visible transcript text was extracted

## Tests

The test suite uses only the standard library:

```powershell
python -m unittest discover -s tests -v
```

## Multi-agent installation

Codex discovers skills under `.codex/skills`. Other tools may scan different
directories. If you want the same skill available elsewhere, copy or symlink
this folder into that tool's skills directory, such as `.opencode/skills` or
`.claude/skills`.

## Privacy

Only analyze share links you are allowed to access. The parser reads public data
exposed by the OpenCode share page or a local HTML file you provide. It does not
authenticate, bypass access controls, or recover data that is not present in the
shared page.

## License

MIT
