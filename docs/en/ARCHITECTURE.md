# How it works and why

[Русский](../ru/ARCHITECTURE.md)

Telegram long polling receives a message. Numeric allowlisting admits a private chat. The inbox persists work before processing it; the dialog resolves a command or optional media search. A SQLite job store queues an idempotent command. Delivery workers call the authenticated loopback Mac agent directly or through SSH. The agent checks the disk and managed ownership, then calls local Transmission RPC. Status returns to the bot, which updates the download dashboard. Plex can index the resulting media folders separately.

The Mac agent isolates filesystem and macOS operations from the conversational code. SQLite allows queued work to survive process restarts without a separate database service. Job identities and confirmation tokens help avoid duplicate actions; ambiguous network outcomes can still require investigation. The disk UUID guard prevents silently writing into a plain folder after an external volume disappears. It cannot repair a faulty drive or guarantee filesystem integrity.

| Code | Responsibility |
|---|---|
| `bot/access.py`, `bot/config.py` | Access and validated installation settings |
| `bot/inbox.py`, `bot/jobs.py`, `bot/delivery.py` | Persistent intake, commands and retries |
| `bot/dialog.py`, `bot/library_dialog.py` | Chat controls and deletion confirmation |
| `bot/search.py`, `bot/providers.py` | Optional identification and source search |
| `bot/progress.py`, `bot/download_dashboard.py` | Estimates and display updates |
| `mac_agent/server.py`, `mac_agent/media.py` | Loopback API, volume guard, scoped media operations |
| `mac_agent/rpc.py` | Transmission authentication and session handshake |
| `mac_agent/naming.py`, `bot/naming_worker.py` | Optional organization and local Plex refresh |

Limitations: primarily Russian UI, two fixed roles (the historical internal second-role name is `mother`), no public-user provisioning, no complete retention policy, no copyright verification, no guarantee of provider uptime, limited platform validation and no proof of unattended power/lid recovery. HTTP handling and local RPC can become slow when storage stalls. Optional image adapters may encounter unsupported Telegram methods and fall back to text. The source tests are not an end-to-end proof for a new installation.
