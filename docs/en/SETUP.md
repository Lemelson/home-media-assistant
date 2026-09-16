# Installation

[Русский](../ru/SETUP.md) · [README](../../README.md)

Start with both processes on one Mac. A separate Linux bot host is optional. The agent uses macOS `diskutil`, the mounted external volume, and Transmission RPC; the bot can run on macOS or Linux. Windows is not supported. Use a maintained OS and Python 3.11–3.13; a historical installation on an older Mac is not a security or compatibility guarantee. Plex is optional and installed separately.

## 1. Obtain and check the code

Clone this repository or use GitHub **Code → Download ZIP**, unpack it and open a terminal in the resulting project folder. Do not run the private installation or copy someone else's environment. Run:

```sh
python3 --version
python3 -m unittest discover -s tests -q
```

The tests need permission to open a temporary loopback HTTP port. No live Telegram credentials or download sources are needed.

## 2. Prepare dedicated storage

In Finder, choose a mounted external drive. The example below assumes `/Volumes/Media`; substitute the actual mount path. Back up important data first. These commands create dedicated folders; do not format the disk or move existing files.

```sh
mkdir -p /Volumes/Media/MediaServer/Movies
mkdir -p /Volumes/Media/MediaServer/TV
mkdir -p /Volumes/Media/MediaServer/Downloads/Incomplete
diskutil info /Volumes/Media
```

Record the **Volume UUID**, not the partition identifier. The application requires the exact mount path, UUID and writable folders; symlinked media directories are rejected. A wrong or missing disk pauses managed activity. ExFAT and slow USB storage can still stall; test with your hardware.

## 3. Configure Transmission

Install Transmission from its official distribution. In its settings enable local RPC with authentication, restrict permitted hosts/addresses to loopback and choose a unique local RPC username/password. RPC must be reachable at `http://127.0.0.1:9091/transmission/rpc`. Do not enable router forwarding or Internet access. Use the dedicated `Downloads/Incomplete` directory for incomplete files. Check the installed Transmission version's settings; labels differ between versions.

Keep Transmission running for the first test. Review its upload/seeding behavior: downloading over BitTorrent may already upload pieces. Only use sources licensed for that behavior.

## 4. Configure the agent

From the project folder:

```sh
mkdir -p agent-state
chmod 700 agent-state
cp examples/agent.example.json agent-state/agent.json
cp examples/transmission-rpc.example.json agent-state/transmission-rpc.json
chmod 600 agent-state/*.json
```

Edit both files locally. Fill in your disk path, UUID, a randomly generated shared token of at least 32 characters, and your Transmission RPC credentials. Use a password manager to generate the token; it must match `MEDIA_AGENT_TOKEN` below. Never paste these files into issues.

Start the agent in its own terminal:

```sh
export AGENT_STATE_DIRECTORY="$PWD/agent-state"
python3 -m mac_agent.server
```

It listens only on `127.0.0.1:18742`. Keep it running. Do not run it as root.

## 5. Configure your Telegram bot

Create a bot with Telegram's official BotFather and keep its token private. Obtain your own numeric Telegram user ID from Telegram's data export or an authenticated Bot API update for your own bot; do not publish the update or send a token to an ID lookup website. One optional additional member is supported. Group chats are rejected. Removing a member ID and restarting removes their access.

```sh
cp .env.example .env
chmod 600 .env
```

Edit `.env` locally. Set `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`, optionally `MEMBER_TELEGRAM_ID`, and the same `MEDIA_AGENT_TOKEN` as in `agent.json`. Leave optional provider keys blank for the first run. On one Mac, keep `MEDIA_AGENT_URL=http://127.0.0.1:18742`.

`.env` is shell syntax. Quote values correctly and source only your own trusted file. Start the bot in a second terminal in the project folder:

```sh
set -a
source .env
set +a
python3 -m bot
```

Open a **private chat** with your bot and send `/start`, `/status`, `/library`. An unlisted account must be denied. Then send a torrent you have permission to download **and share**. Follow [usage](USAGE.md).

## 6. Optional services

| Setting | Effect |
|---|---|
| `OPENROUTER_API_KEY` + `OPENROUTER_MODEL` | Sends title requests and limited conversation context to OpenRouter and its selected model provider; choose an available model supporting structured JSON responses |
| `EXA_API_KEY` | Adds external evidence search for title identification; uses the OpenRouter resolver |
| `PROWLARR_API_KEY` | Uses your local Prowlarr on port 9696; requires the resolver and independently configured, authorized sources |
| `ENABLE_VOICE=1` | Enables external speech transcription; requires `GROQ_API_KEY` or a compatible OpenRouter transcription model in `OPENROUTER_STT_MODEL` |
| `ENABLE_REMOTE_IMAGES=1` | Permits remote images, including search-result images; requires you to verify display rights and provider conditions |
| `TMDB_READ_ACCESS_TOKEN` / `TMDB_API_KEY` / `SERPER_API_KEY` | Optional image providers; used only when images are enabled; Exa images take precedence if Exa is enabled |

Provider availability, features, pricing and data retention can change. Verify the current terms directly; the repository supplies no accounts or entitlement. No indexers are configured by this project. Do not use it to bypass access controls, service bans, subscriptions or geographic restrictions. When AI is enabled, a background worker may also send managed filenames and paths for organization; read [privacy](PRIVACY.md).

For Plex, create movie and TV libraries pointing to `MediaServer/Movies` and `MediaServer/TV`. Enable the native library scanning appropriate for your version. The naming integration can request a local Plex refresh using the logged-in macOS user's existing Plex preferences. The program does not provide a Plex subscription or override remote-playback entitlements. Playback itself happens in your media player, not Telegram.

## Separate bot host

Keep the agent on the Mac. Establish an SSH connection **from the Mac** to an SSH account you control on the bot host:

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:18741:127.0.0.1:18742 bot-host
```

`bot-host` is your locally configured SSH alias. Verify the server's host key; use your own restricted SSH key. On the bot host set `MEDIA_AGENT_URL=http://127.0.0.1:18741`. The remote listener must stay loopback-only. Never copy your private SSH key into the repository.

## Stopping, updates and recovery

For this first release, foreground start is the supported documented path. Stop with Ctrl-C. Download jobs may continue in Transmission after the bot stops; stop them separately if necessary. Back up the private state directories before updating; replace only the source code, run tests and restart both processes. Do not enable automatic updates from an arbitrary Git branch.

`deploy/home-media-deploy` is an inherited advanced Linux deployment helper, not a complete installer. It assumes an existing service account, systemd unit, repository mirror and fixed directories. Do not run it without reviewing and provisioning those prerequisites.

Automatic login, startup services, sleep, a closed lid, power loss and network reconnection require separate acceptance tests on your machine. A running Python process does not prove unattended operation. This release does not modify your power settings or install startup services.
