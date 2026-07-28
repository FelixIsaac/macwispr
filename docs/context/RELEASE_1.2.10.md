# MacWispr 1.2.10 (stable)

**Version:** 1.2.10  
**Channel:** production (`main` + Sparkle appcast + GitHub Latest)  
**Base:** 1.2.9 leaderboard + waveform

## What's new

| Change | Notes |
|--------|--------|
| **SuperGrok STT** | Optional cloud dictation via Grok CLI login (`~/.grok/auth.json`) |
| **Consent first** | One-shot “Use Grok for voice dictation?” — never silent |
| **Live streaming partials** | Same protocol as Grok Build: stream PCM → `wss://api.x.ai/v1/stt` → HUD types while holding ⌥Space |
| **Settings / chip** | Grok provider only appears when a Grok session exists or user already consented |
| **Privacy** | Documents Grok path: audio to xAI after consent; SuperGrok usage pool |

## Intentionally not included

- OpenAI Codex OAuth reuse (not ready)
- OOM crash hardening (tracked as [#25](https://github.com/vasanthsreeram/macwispr/issues/25))
- Polish LLM default remains **off**

## Billing note (product)

Grok STT uses the user’s SuperGrok / Grok Build OAuth session. It is **included subscription usage** (weekly SuperGrok pool), not MacWispr-billed, and not free unlimited. Free/X Basic users should not get a working session without SuperGrok.

## Ship

```bash
git tag -a v1.2.10 -m "MacWispr 1.2.10"
git push origin v1.2.10
# Release workflow: sign, notarize, GitHub Latest, appcast
```
