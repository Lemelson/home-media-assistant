# Detailed operations guide: a spare MacBook as a home media server

[Русский](OPERATIONS.ru.md) · [Installation commands](../README.md) · [Publication and rights](PUBLICATION.md)

This explains the public project, not a particular household's configuration. Names and paths are illustrative. Read this guide first, then follow the installation README in order. Do not execute the entire document as one script.

## 1. What the MacBook hosts

The Mac runs ordinary applications continuously: the agent accepts commands, Transmission transfers files, and optional Plex serves a library. This is a home computer acting as a server; it does not need to host a public website. Telegram provides remote control after installation. Older hardware is useful only while its OS and applications remain supportable and its power, storage and cooling are reliable.

An external volume holds the media; the internal drive holds the OS and small application state. This project is not a backup system. Keep independent backups of valuable recordings and do not format an existing disk merely to try the project. The volume UUID helps distinguish the intended disk from another volume with the same display name.

The Mac must be awake, connected and able to access its storage. Closed-lid operation, login after reboot, FileVault unlocking and power recovery depend on the machine. This guide does not require disabling encryption or OS protections. A user LaunchAgent depends on a user session and does not establish unattended operation before login.

## 2. Choose a topology

| Question | One Mac | Linux bot plus Mac storage |
|---|---|---|
| Processes | Bot, agent and Transmission on Mac | Bot on Linux; agent and Transmission on Mac |
| Separate hosting | Unnecessary | An accessible Linux machine, optionally a rented VPS |
| Mac asleep | Bot and file operations unavailable | Bot may respond while Mac operations await recovery |
| Media location | Mac disk | Mac disk; no media copy required on the VPS |
| Additional maintenance | Local processes | Two hosts, SSH credentials and tunnel recovery |
| Suggested starting point | First installation | After a successful local installation |

The separate server keeps the conversation interface and command queue available during a home-machine outage. It does not wake the Mac, speed up its disk or remove provider limits. In this design the bot does not relay the video library through the VPS. Transmission on the Mac transfers the content. The SSH tunnel carries agent control requests and responses; it does not anonymize BitTorrent traffic or grant content rights.

## 3. Follow a request

1. Telegram delivers a message. The bot checks the numeric user ID and chat type.
2. An authorized direct link can be handled without AI. Title recognition and release search are separate operations requiring optional configured services.
3. The bot stores card context and commands locally; each card belongs to its own request.
4. The bot calls the agent with a shared secret. With two hosts this passes through SSH.
5. The agent checks the expected storage volume and calls local Transmission RPC using a separate username and password.
6. Transmission transfers and stores data; the agent reports state and the bot updates progress.
7. Optional Plex reads the completed library directories. Playback takes place in a media player, not in the Telegram control chat.

Recognizing a title proves neither availability nor permission to transfer a work. Do not add unreviewed sources to test connectivity.

## 4. Connection map

| Caller | Destination | Purpose |
|---|---|---|
| Bot | Telegram HTTPS API | Messages and responses |
| Bot on same Mac | `127.0.0.1:18742` | Agent HTTP with Bearer authentication |
| Bot on Linux | Linux `127.0.0.1:18741` | Reverse SSH tunnel entry |
| SSH client on Mac | Your SSH server | Encrypted control channel |
| Mac agent | `127.0.0.1:9091/transmission/rpc` | Transmission control |
| Bot with optional search | Bot host `127.0.0.1:9696` | Prowlarr |
| Optional features | Selected external HTTPS APIs | Recognition, search, voice or images |

Loopback means the machine running the command. Server port 18741 and Mac port 18742 are different endpoints. The public bot accepts only a loopback agent URL: use a tunnel instead of substituting a public address. Loopback does not protect against administrators or malicious processes on the same host.

Management ports are different from P2P transport ports. Do not expose agent, Transmission RPC or Prowlarr management to the Internet. Start Plex on the local network; remote playback is a separate Plex configuration and access review.

## 5. Configuration and state

| File or directory | Host | Contents | Publish? |
|---|---|---|---|
| `.env` | Bot host | Telegram token, IDs, agent token, optional API keys | No |
| `agent.json` | Private agent directory on Mac | Volume path, UUID, shared token | No |
| `transmission-rpc.json` | Same agent directory | RPC username and password | No |
| `STATE_DIRECTORY` | Bot host | Dialog, queue and operational state | No |
| `AGENT_STATE_DIRECTORY` | Mac | Agent database and configuration | No |
| Reviewed source and `.example` files | Repository clone | Code and empty templates | After review |

Telegram token, agent token, RPC password and SSH key have different roles. Do not reuse one credential everywhere. The agent token must match between `agent.json` and `MEDIA_AGENT_TOKEN`. Read your own disk UUID. Do not publish environment dumps, populated configuration or credential screenshots.

For persistent services keep state outside the clone. The systemd example uses `/etc/home-media-assistant` and `/var/lib/home-media-assistant`. Prefer absolute paths because relative ones depend on the working directory. Python does not automatically load `.env`: the manual instructions source it in a shell; systemd uses `EnvironmentFile`.

## 6. First-run sequence

### A. Verify the Mac independently

Install Python and Transmission from official sources. Check `python3 --version`, inspect the intended volume with `diskutil info /Volumes/Media` (substitute your path), and verify your user can write to the chosen directories. Configure local RPC port 9091 with its own authentication. UI and daemon settings differ: follow the documentation for your installed Transmission version.

Try a small file that you created or are explicitly authorized to transfer directly in Transmission, then pause it. This separates disk, client and source failures from bot failures. Stopping Python does not stop Transmission.

### B. Start the agent

Copy and populate the two JSON templates as described in the [README](../README.md), then run the agent in a terminal. Do not run it as root to bypass file permissions. On the Mac:

```sh
lsof -nP -iTCP:18742 -sTCP:LISTEN
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18742/health
```

An unauthenticated request should return `401`. That confirms an authenticated endpoint is reachable; it does **not** prove disk or RPC health. A connection failure/`000` means no HTTP response was obtained. Keep authentication enabled and use the bot's `/status` for the subsequent functional check.

### C. Start a local bot

Create your bot through BotFather, set your numeric ID and populate `.env` with optional integrations disabled. Run the README commands. Keep only one process polling the same Telegram bot. If using `getUpdates` to obtain your ID, follow the [official Bot API](https://core.telegram.org/bots/api#getupdates). Keep the token local; responses can contain personal messages and should not be attached to issues.

Check `/start`, `/status`, `/library`, rejection of an unrelated account and group chat, then a small authorized transfer, pause and resume. Test deletion only on disposable files. Enable external services one at a time afterwards.

### D. Optionally move only the bot

Stop the local bot, deploy the same source edition on Linux and create private settings/state there. If migrating your own database, stop its writer and use a private transfer channel, never Git. Media stays on the Mac. Do not run two polling instances with the same bot token.

Set up an SSH alias `bot-host` using your host, account and a dedicated key. Verify the server fingerprint through a trusted administrator channel. Do not disable host-key verification. On the Mac:

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:18741:127.0.0.1:18742 bot-host
```

`-N` avoids a remote command. `-R` creates a server listener leading back to the Mac agent. Verify the actual bind address and server `GatewayPorts` policy preserve loopback-only access. Keepalive detects a failed channel; it does not itself restart SSH. See the [OpenSSH manual](https://man.openbsd.org/ssh).

On Linux inspect `ss -ltn`, then make the same unauthenticated request to `http://127.0.0.1:18741/health`, expecting `401`. Set the bot's agent URL to port 18741 and check `/status`. Fix a missing SSH tunnel before changing unrelated credentials.

## 7. Persistent services

The [systemd example](../examples/home-media-bot.service) requires an existing `media-bot` user, accessible code/Python and a private `/etc/home-media-assistant/bot.env`. Prepare those first. After checking every path, an administrator can run these on Linux from `deployment-reference`:

```sh
sudo install -m 644 examples/home-media-bot.service /etc/systemd/system/home-media-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now home-media-bot.service
sudo systemctl status home-media-bot.service
```

Inspect errors locally with `journalctl -u home-media-bot.service -n 50 --no-pager`; logs may contain sensitive context. Stop with `sudo systemctl stop home-media-bot.service`; disable startup with `sudo systemctl disable home-media-bot.service`. See the installed `man systemctl` for the host's version.

For Mac, edit all three absolute paths in the [LaunchAgent](../examples/org.home-media-assistant.agent.plist). Do not leave placeholder paths or put `~` in place of absolute plist paths. Stop the terminal agent after proving it works. Save the plist in `~/Library/LaunchAgents/org.home-media-assistant.agent.plist`, then:

```sh
plutil -lint "$HOME/Library/LaunchAgents/org.home-media-assistant.agent.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/org.home-media-assistant.agent.plist"
launchctl print "gui/$(id -u)/org.home-media-assistant.agent"
```

Unload with `launchctl bootout "gui/$(id -u)/org.home-media-assistant.agent"`. This starts only the agent. Transmission startup and SSH reconnection remain separate configuration tasks. No universal watchdog is installed by this guide. Test user login, disk mount, network, Transmission, tunnel, `/status` and an authorized transfer after reboot. See [Apple's launchd guide](https://support.apple.com/guide/terminal/script-management-with-launchd-apdc6c1077b-5d5d-4d35-9c19-60f2397b2369/mac).

## 8. Troubleshooting

| Symptom | First checks |
|---|---|
| Bot silent | Process, Telegram connectivity/token, ID and duplicate polling instance |
| Title card but no results | Recognition succeeded; separately inspect source and search cooldown |
| Search retries | Wait for the bounded cycle; duplicate clicks do not remove a provider block |
| Agent unavailable | Mac process and port, then Linux tunnel and port |
| Bot receives `401` | Matching agent tokens; do not substitute the Telegram token |
| Disk unavailable | Mount, UUID and permissions; do not change UUID to bypass the guard |
| RPC unavailable | Transmission process, port 9091 and credentials; the adapter handles the session handshake |
| Transfer stalled | Transmission state, free space and authorized source/peer availability |
| File absent from Plex | Library directory, reading permissions and library scan |
| Failure after reboot | User session, services, disk, Transmission and tunnel separately |

Search has at most four attempts within two minutes. A longer provider cooldown can mean fewer attempts. The retry button belongs to its original film even after later requests, subject to the card lifetime documented in the README. Retries do not promise a result or bypass access denial.

## 9. Updates, backups and support reports

Record the current commit, stop bot/agent writers and back up private state before updating. Copy SQLite only with writers stopped or a suitable database backup mechanism; copying one live database file may be incomplete. Back up valuable media separately. Start the new version with consistent paths, then check status, library and a small authorized scenario. Rollback requires previous code and compatible state; Git does not roll back a database.

For an issue provide OS/Python/application versions, commit, component, error code and synthetic reproduction. Remove IDs, addresses, tokens, private filenames and screenshot metadata. Do not attach SQLite, `.env`, cookies, SSH config, API dumps or actual torrent files. If a credential was exposed, revoke it first: deleting a line or commit does not invalidate it.

## 10. Component documentation

- [Python](https://www.python.org/downloads/): choose an installer for your OS.
- [Transmission RPC](https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md): control protocol and session handshake; the public adapter uses local RPC.
- [Apple launchd](https://support.apple.com/guide/terminal/script-management-with-launchd-apdc6c1077b-5d5d-4d35-9c19-60f2397b2369/mac): user agents and system processes.
- [Telegram Bot API](https://core.telegram.org/bots/api): tokens, updates and API limits.
- [OpenSSH](https://man.openbsd.org/ssh): forwarding and connection options.

Check component version support before installing. Mocked project tests do not prove compatibility with every future Transmission or Plex release.
