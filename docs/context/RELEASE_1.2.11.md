# MacWispr 1.2.11 (stable)

**Version:** 1.2.11  
**Channel:** production (`main` + Sparkle appcast + GitHub Latest)  
**Base:** 1.2.10 SuperGrok STT

## What's new

| Change | Notes |
|--------|--------|
| **Long dictation** | Overlapping windows + PCM spill. Qwen is no longer capped at 256 tokens for the whole take. Parakeet no longer keeps only the last 30s. |
| **Idle unload** | Local ASR/polish GPU weights drop after idle (polish ~2 min, ASR ~8 min). Next hotkey reloads from disk cache. Cloud never keeps local weights resident. |
| **OOM (#25)** | Memory-pressure unload + refuse 1.7B when RAM is tight. Banner instead of crash. |
| **Grok quota (#26)** | Weekly-limit / 429 maps to an actionable banner, not “bad response from the server.” |
| **⌘Q / ⌘W (#15)** | ⌘W closes the dashboard (stays in the menu bar). ⌘Q quits. |
| **Dashboard clicks (#21)** | AppKit hit-targets for Home chips / mic pickers (macOS 26 `_ButtonGesture` SIGSEGV). |

## Intentionally not included

- Cloud polish training flywheel (#24) — still R&D
- Appcast / Sparkle until this tag is published

## Local test (this machine)

```bash
# Installed ad-hoc to /Applications (not repo dist/)
/Applications/MacWispr.app/Contents/MacOS/MacWispr --self-test
# 2026-09-08: ALL PASSED (status item, model, hold/toggle, synthetic + CGEvent hotkey)
```

## Ship

```bash
git tag -a v1.2.11 -m "MacWispr 1.2.11"
git push origin v1.2.11
# Release workflow: sign, notarize, GitHub Latest, appcast
```
