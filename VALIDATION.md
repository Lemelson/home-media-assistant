# Publication verification — 2026-09-14

This is a separate source-only export with fresh Git history. It contains reviewed Python source and synthetic tests, bilingual documentation, empty configuration templates, an explicit file manifest and a bounded publication scanner. Original private Git history, operational notes, secrets, SSH material, databases, media, archives and release/deployment records are excluded.

Public-release changes: configurable bot identity; numeric owner/member access at startup; immediate rejection after removing a member from configuration; loopback-only agent URL validation; minimum shared-token length; configurable agent state path; explicit voice/image opt-in; disabled source-image fallback when images are off; text link previews disabled by default. Original operation and private services are not changed by creating this export.

Evidence: the inherited 278-test suite initially had two loopback bind failures in the restricted environment. After allowing temporary local test servers, the expanded suite passed. Final exact counts and local runtime are recorded below before packaging. Tests use synthetic state and mocked external services, plus loopback HTTP. They do not use the real household installation or authenticate with Telegram/providers.

Limits: the public startup has not been exercised against a fresh live Telegram bot and physical external disk. Linux CI and the declared Python compatibility matrix require remote CI results. The predominantly Russian UI has not been fully localized. There is no independent complete security audit or legal certification. Provider rights, data retention, terms, geographic availability and actual authorized media sources remain operator-specific.

Состав публикации отделён от частной установки. Тесты — локальные проверки кода и искусственного сценария, а не доказательство запуска нового Telegram-бота на физическом диске. Полной локализации UI, независимого аудита и юридической сертификации нет.

## Final local result

- macOS, Python 3.14.6: **288 tests passed**, 3.243 seconds, including authenticated loopback HTTP and the synthetic download/control/deletion scenario.
- Publication scanner: **PASS**, 113 reviewed text files; no matches for its credential/private-path/email rules.
- Additional targeted personal-name scan: zero matches in the export; relative documentation links: zero broken links.
- The scanner does not prove absence of all secrets or vulnerabilities. Synthetic secret-shaped fixture values are not production credentials.
- Python emitted resource-cleanup warnings from inherited tests. The suite exited successfully; this is not a claim of warning-free execution.
- GitHub publication and remote CI were not available during preparation because network requests timed out. Check the actual remote before claiming a published release.

## Maintenance guard update — 2026-09-14

The publication check now inspects all reachable commit snapshots, author/committer identities and commit messages. It rejects private runtime paths even if they are added to the manifest, specific hardware identifiers, non-example IPv4 addresses, symlinks and unsafe Git tree entries. Two public connectivity constants are explicitly reviewed only in the recovery module and scanner exception list. This is still a bounded pattern-based check, not proof that any future arbitrary text is non-sensitive; content review remains mandatory.

Regression evidence includes a temporary repository in which a synthetic token is committed and then removed: the current tree passes, but history checking blocks publication. The updated suite passed **292 tests in 3.796 seconds**, on macOS with Python 3.14.6. The reviewed manifest now contains **115 files**, including EN/RU publication/discoverability guidance. Remote GitHub publication, CI and actual scheduled-run execution remain separate checks.

## Workflow clarification — 2026-09-14

Maintenance means checkpoints during user-assigned work, not scheduled autonomous work. The documentation and workflow now reflect that distinction. The extra remote full-history CI step was removed; the local publication guard is retained for actual pushes. Local commits need neither network access nor a full history scan. This documentation/configuration-only change was checked for valid local links, clean diff formatting and publication-tree contents; the runtime test suite was not unnecessarily repeated.

## Current reference edition — 2026-09-16

The `deployment-reference` directory has **417 passing tests** (macOS / Python 3.14.6, 5.615 seconds); the original public root has **292 passing tests** (3.693 seconds). The installed code was read separately from the bot and Mac agent; only reviewed source was exported. Private configuration and state were never copied into the public tree. Differences and test provenance are documented in [SNAPSHOT.md](deployment-reference/SNAPSHOT.md).

The exact final file manifest and outgoing history are checked before the public push. Additional review found no private installation labels, personal home paths or operator network addresses in the export. Source hashes, Markdown links and the generic plist structure are checked locally. Scanner results do not constitute a comprehensive security audit or legal guarantee. Remote repository visibility, pushed SHA and CI are verified separately after publication.
