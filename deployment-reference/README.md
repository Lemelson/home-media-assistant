# Deployment reference

[Русский](README.ru.md) · [Project overview](../README.md) · [Legal considerations](../docs/en/LEGAL.md)

A sanitized source edition derived from a running installation, prepared in September 2026. This is code and a reproducible setup guide, not a server backup. It contains no operator credentials, media inventory, chat logs or configured content sources.

## Detailed guides

- [Architecture, connections, persistent services and troubleshooting](docs/OPERATIONS.md).
- [Publication scope, licensing and personal data](docs/PUBLICATION.md).

The installation sequence follows below; the guides explain the reasons and expected outcomes of each stage.

## Purpose and layout

Control your private home library from a private Telegram chat: submit authorized torrents or magnet links, monitor transfers, pause/resume, choose seasons and browse managed files. Optional providers identify titles and search sources you configure independently. Playback happens in Plex or another player, not Telegram.

Use recordings you own, material expressly licensed for the intended transfer, or public-domain material whose status you have verified in the relevant jurisdictions. BitTorrent describes a transfer protocol; it does not establish rights to a file. Clients can upload pieces while downloading.

| Component | Location | Responsibility |
|---|---|---|
| `bot/` | Linux host or the same Mac | Telegram, access control, search, persistent commands, progress cards |
| `mac_agent/` | Mac with media storage | Volume checks, local Transmission RPC, file operations and library |
| Transmission | Mac | File transfers, including operator-configured upload/seeding |
| External volume | Mac | Dedicated Movies, TV and Downloads/Incomplete folders |
| Prowlarr, optional | Bot host | Independently configured authorized search sources |
| Plex, optional | Mac | Library and playback, under its own terms |
| SSH reverse tunnel | Mac to bot host | Loopback-only connectivity to the agent |

One Mac is enough to start. A Linux host does not need a copy of your media. Network availability is needed for Telegram and any enabled providers.

## Public adaptations

Search/retries, independent cards, command queues, progress forecasting and library management come from the installed code. Startup uses your numeric Telegram IDs, generic storage labels and configurable private state paths. Remote images and voice processing are off by default; an AI model must be selected explicitly.

Authenticated browser sessions, site-specific browser loaders, challenge-page tooling, preconfigured indexers, proxy/VPN profiles and captured search datasets are omitted. Extended authenticated website descriptions are therefore not configured here. Core Prowlarr search works independently. Tests contain synthetic data; titles in tests are not a download catalogue.

The repository's top-level `bot/` and `mac_agent/` are the earlier baseline public edition. Do not mix their files with this directory. Run the commands below from `deployment-reference` for the current features.

## 1. Prerequisites and tests

Use a maintained macOS version for the agent, Python 3.11–3.13, Transmission with local RPC, available disk space and dedicated media folders. The bot can also run on Linux. Python code uses the standard library. Bring your own Telegram and optional API accounts; verify their terms, regional availability and costs. Older hardware is not a support or security guarantee.

```sh
git clone https://github.com/Lemelson/home-media-assistant.git
cd home-media-assistant/deployment-reference
python3 --version
PYTHONPATH=.:tests python3 -m unittest discover -s tests -q
```

Tests need temporary loopback ports, not real provider credentials or downloads. Do not change system Python or power settings just for the first run.

## 2. Storage and Transmission

Choose a mounted drive and record its Volume UUID using `diskutil info`. The example path is a placeholder:

```sh
mkdir -p /Volumes/Media/MediaServer/Movies
mkdir -p /Volumes/Media/MediaServer/TV
mkdir -p /Volumes/Media/MediaServer/Downloads/Incomplete
diskutil info /Volumes/Media
```

These commands do not format storage. Back up important data. Configure authenticated Transmission RPC at `127.0.0.1:9091`; do not expose it to the Internet. Keep Transmission running manually for the first test. Verify permission for downloading **and uploading** before starting a transfer.

## 3. Agent on the Mac

```sh
mkdir -p agent-state
chmod 700 agent-state
cp ../examples/agent.example.json agent-state/agent.json
cp ../examples/transmission-rpc.example.json agent-state/transmission-rpc.json
chmod 600 agent-state/*.json
```

Fill in your volume path, UUID and RPC credentials. Generate a random shared agent token of at least 32 characters using a password manager. The same token is needed by the bot. Never commit these files.

```sh
export AGENT_STATE_DIRECTORY="$PWD/agent-state"
python3 -m mac_agent.server
```

The authenticated agent listens on `127.0.0.1:18742`. Leave the terminal open and do not run it as root.

## 4. Telegram bot

Create your own bot through official BotFather. Obtain your numeric Telegram ID from your Telegram export or an authenticated Bot API update for your own bot. Never submit the token to a third-party ID-lookup website.

```sh
cp .env.example .env
chmod 600 .env
```

Set `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`, optional `MEMBER_TELEGRAM_ID`, and the same `MEDIA_AGENT_TOKEN`. For a single Mac, keep `MEDIA_AGENT_URL=http://127.0.0.1:18742`. Choose a private `STATE_DIRECTORY`, separate from agent state. Leave optional APIs blank and keep `ENABLE_VOICE=0` and `ENABLE_REMOTE_IMAGES=0` for the first test.

```sh
set -a
source .env
set +a
python3 -m bot
```

An environment file contains shell syntax: source only your own trusted file. In your private bot chat, try `/start`, `/status` and `/library`. An unlisted account and group chat must be denied. Then test a file you are independently authorized to transfer.

## 5. Separate Linux host

Copy this source directory to a Linux host under a dedicated unprivileged service account, with its own environment file and private state directory. Keep the agent and Transmission on the Mac.

Configure your own SSH alias `bot-host`, verify the host key and use a dedicated restricted key. From the Mac:

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:18741:127.0.0.1:18742 bot-host
```

Set `MEDIA_AGENT_URL=http://127.0.0.1:18741` on the Linux host. Its SSH server must allow this loopback reverse forward. Do not publish the agent, RPC or Prowlarr ports. Commands remain queued when the connection is unavailable; verify recovery on your installation.

## 6. Optional identification and search

Set `OPENROUTER_API_KEY` and an explicitly selected `OPENROUTER_MODEL`. Optionally add `EXA_API_KEY` for title evidence. Install your own Prowlarr next to the bot on loopback port 9696, configure sources you have independently checked, and set `PROWLARR_API_KEY`. Test the indexer first, then try a title in Telegram. No source accounts or source catalogue are provided.

Voice requires `ENABLE_VOICE=1` and an appropriate `OPENROUTER_STT_MODEL`. Images require `ENABLE_REMOTE_IMAGES=1` and your Exa/TMDB/Serper configuration. Check display rights and attribution conditions first; an API key alone is not permission for every image. Remote images are disabled by default in the public startup path.

Providers receive requests and, when relevant features are enabled, voice, context, filenames and paths. Local databases store IDs, history, commands, metrics and caches without application-level encryption. See [data flows and deletion](../docs/en/PRIVACY.md).

## 7. Search retries and old cards

The card shows the first attempt. A temporary failure updates the same card with the reason, waiting period and next attempt. There are at most four attempts within a two-minute search budget; provider cooldown can reduce this count. Repeated clicks are coalesced and successful partial results are retained.

If search still fails, the card shows the attempt count and a retry button tied to that film. Later title requests do not change its target. State survives process restart. Cards retain the existing seven-day lifetime, renewed after a failed cycle. Successful empty results are distinguished from unavailable providers. The second-member mode can automatically select an eligible movie release, so enable search only for sources whose transfer rights you have checked.

## 8. Startup, updates and acceptance

Get the foreground setup working first. Then adapt the [systemd example](examples/home-media-bot.service) with your service account, working directory, environment file and Python path. On macOS, adapt the [LaunchAgent example](examples/org.home-media-assistant.agent.plist). The examples are not installed automatically and contain no device-specific paths. The optional watchdog requires matching agent/Transmission launchd labels and is not enabled by this guide.

Stop the bot before replacing source code; keep private state/configuration out of Git and back them up locally first. Run tests and verify `/status` after restart. Rollback means restoring the previous source directory; database compatibility depends on the update. Do not auto-update from an unreviewed branch.

Test sleep, closed-lid behavior, removed storage, lost network and reboot recovery separately. A running process does not prove unattended operation. Stopping the bot does not stop transfers already running in Transmission.

The Downloads dashboard shows current disk space, remaining queue size (including paused downloads), projected free space or shortage, and a conditional time range from each film’s downloaded bytes over the last 10 minutes, including stalls. Missing metadata or stale status suppresses unreliable estimates. The safety reserve can pause downloads before the disk fills.
