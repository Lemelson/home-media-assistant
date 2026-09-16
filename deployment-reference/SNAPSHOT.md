# Source reference and validation

This September 2026 source edition is derived from the installed bot and installed Mac agent. It is intentionally **not** a byte-for-byte server image. Private paths, account-bound startup and device labels have been replaced with public configuration. No private release identifiers or operational records are included.

Included: 35 bot Python modules, 12 Mac-agent modules, synthetic tests, generic examples and EN/RU setup guides. `SOURCE_FILES.json` records SHA-256 values for the published source, not for any private configuration.

Adaptations:

- Existing reviewed numeric-ID access and configuration validation are reused.
- Voice/images require explicit opt-in; AI model selection is explicit; Telegram text previews are off.
- Server/account identities and disk labels are removed; state paths are operator-configurable.
- Site-specific authenticated browser loaders and their component tests are not distributed. Generic title matching, result parsing, search retries and independent card state remain.
- Captured search corpora are omitted. The season-grounding fixture is synthetic; its test is named accordingly.
- Two older tests that rejected all multi-season packs were updated to check the installed agent's actual safety contract: remain paused until requested files are known. Existing tests also verify selected files before transfer.

Validation on macOS / Python 3.14.6: **417 tests passed** with external services mocked and temporary authenticated loopback HTTP servers. The earlier root edition separately passed **292 tests**. CI exercises both editions on Linux and macOS with Python 3.11 and 3.13. Remote CI results must be checked separately.

Privacy review covers the exact manifest, source diff, documentation, synthetic fixtures, and all outgoing Git history. No matching secrets/private deployment identifiers were found by the available rules and additional review. This is bounded evidence, not a claim that all possible sensitive information or vulnerabilities can be detected. No fresh public Telegram deployment or physical-disk acceptance is implied by unit/integration tests. No legal certification is provided.
