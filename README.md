# Home Media Assistant

**English** · [Русский](README.ru.md)


[Detailed architecture and operations](deployment-reference/docs/OPERATIONS.md) · [Publication and rights](deployment-reference/docs/PUBLICATION.md)

## Current deployment reference

The separate [deployment-reference directory](deployment-reference/README.md) contains sanitized current bot and Mac-agent code, search retries, independent film cards, and a step-by-step single-Mac or Linux-plus-Mac setup. It is a source edition with documented public adaptations, not an image of a private server. Use that directory for current features; the root implementation remains the earlier baseline.

A self-hosted Telegram assistant for a private media library on macOS: queue authorized downloads, monitor progress, organize files, and browse your library. Reuse a spare Mac and an external drive with Transmission and optional Plex integration.

**Experimental release.** Documentation is bilingual; the bot's conversational interface and most buttons are currently Russian. English-speaking operators can use the slash commands and the [button glossary](docs/en/USAGE.md). Full English UI localization is not implemented. This is a software toolkit, not a hosted service or a media catalogue.

## Who it is for

People comfortable with a terminal who want to manage their own small home library from a private Telegram chat. Useful for personal recordings and media explicitly licensed for the intended copying and sharing. Supports one owner and one optional household member. It is not designed for a public download service or multi-tenant hosting.

## What it does

- Accepts a `.torrent` file or magnet URI you are authorized to use.
- Keeps commands in a local SQLite queue and retries when the Mac is unavailable.
- Displays progress, speed estimates, pause/resume and priority controls.
- Checks the external volume UUID and expected folders before managing downloads.
- Requires confirmation before a supported deletion; restricts management to tracked media.
- Optionally identifies titles with an external AI provider and searches your separately configured Prowlarr instance.
- Optionally organizes completed media and asks a local Plex server to refresh its library.

AI can identify a title incorrectly. A matching search result does **not** establish distribution rights. Review your sources before enabling search; eligible movie matches can be queued automatically after title selection.

## Get started

1. Read [installation](docs/en/SETUP.md) and [data flows](docs/en/PRIVACY.md).
2. Install Python 3.11–3.13 and Transmission on your Mac. The runtime uses the Python standard library; no Python packages are required.
3. Configure your own bot, numeric Telegram user IDs, shared agent token and disk UUID.
4. Start the loopback agent and the bot, then use `/start`, `/status` and `/library`.
5. Test with content whose permission you have independently verified.

See [usage](docs/en/USAGE.md), [architecture and limitations](docs/en/ARCHITECTURE.md), [legal considerations](docs/en/LEGAL.md), [security reporting](SECURITY.md) and [contributing](CONTRIBUTING.md).

## Privacy and permissions

No bot credentials, server accounts, private installation history, media files, torrent catalogues or preconfigured indexers are distributed. Telegram is required and receives chat content. Optional AI/search/voice/image providers receive data when enabled. Local databases contain personal information and are not encrypted by this application. [Details and deletion instructions](docs/en/PRIVACY.md).

This repository does not grant rights to films, music, artwork, provider services or third-party software. BitTorrent can upload while downloading. A private library, a paid subscription or a disclaimer is not universal permission to copy or redistribute. [Legal notes and primary sources](docs/en/LEGAL.md) explain the limits; no jurisdiction-wide compliance guarantee is offered.

## Development

```sh
python3 -m unittest discover -s tests -q
python3 scripts/check_public_tree.py
```

Tests use synthetic data, mocks and temporary loopback servers. They do not prove that your Telegram account, external disk, providers, sleep settings or power recovery work. The publication verification record is in [VALIDATION.md](VALIDATION.md).

Code: [MIT license](LICENSE). Third-party services and applications have their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Work checkpoints and search visibility: [publication policy](docs/en/PUBLICATION.md).

Feature and fix history: [development checkpoints](CHANGELOG.md).
