# Data flows and private operation

[Русский](../ru/PRIVACY.md)

This is an inventory for an operator, not a claim that the system is anonymous or a completed policy for a public service. The repository supplies no hosted backend or maintainer telemetry endpoint.

| Component | Data it may receive/store |
|---|---|
| Telegram | User and chat IDs, messages, attachments, voice, bot responses, filenames/status shown in chat; bots are not end-to-end encrypted secret chats |
| Bot state directory | SQLite access attempts, two-member registry, conversation context, queued commands, search state, delivery/progress records and identifiers |
| Mac agent state | Download ownership, torrent identifiers/metadata, managed filenames/paths and progress history; local credentials in JSON |
| Transmission and peers | Torrent identifiers, files/pieces and network addresses; peers can see the connection IP |
| Plex (optional) | Library metadata and server/account activity according to its settings and terms; local integration reads the user's existing Plex token |
| OpenRouter + model provider (optional) | Requests and limited context for identification; filenames/paths for background media naming; audio if transcription is selected |
| Exa/Prowlarr (optional) | Search queries; Prowlarr forwards queries to your configured indexers; Exa is an external service |
| Groq (optional) | Voice audio for transcription |
| TMDB/Serper/image hosts (optional) | Image queries and requests; Telegram may fetch supplied remote image URLs |

Blank provider keys disable their integrations. Voice and remote images additionally require explicit flags. Disabling them does not prevent Telegram itself from receiving a voice message a user sends. The application does not encrypt its SQLite databases; filesystem permissions, host account security, disk encryption and backups are the operator's responsibility. Provider-side retention and international transfers are outside this application's control.

## Minimize exposure

Use a dedicated private bot for your household. Set numeric IDs, keep agent/RPC on loopback, and use a restricted SSH tunnel if necessary. Keep `.env`, `agent-state`, `runtime`, SSH keys, backups and diagnostic exports out of Git. Do not post `/access` output, database contents or a Telegram screenshot with identifiers. Disable unused APIs and review the data policy of every enabled provider.

The code contains some bounded histories but **does not implement a uniform retention deadline or complete per-person erasure workflow**. Access attempts and durable job data can persist. Do not advertise automatic GDPR compliance. Before offering access beyond a household, design and validate the necessary retention, deletion, notice and access procedures.

## Resetting a private installation

Stop the bot and agent, stop pending Transmission transfers if desired, and revoke unused provider credentials. Back up anything you need privately. To erase application records, remove only your configured bot and agent state directories, after confirming their paths. This resets authorization and loses queued jobs and download ownership mappings; it does not delete the media library, Telegram messages, Transmission records, Plex data or external provider copies. Existing downloads may require manual management after a reset. Handle those systems separately using their supported controls and applicable retention rules.

## Public source privacy

Publishing from an existing GitHub account visibly links the repository to that account. A fresh Git history and GitHub `noreply` commit address avoid exposing old commits or a personal commit email; they do not hide a public profile, contribution activity, forks or cached copies. This release's exclusion scan is bounded evidence, not a guarantee that every future contribution is free of secrets. If a credential leaks, revoke it with the issuer; deletion alone is insufficient.

The recovery helper also makes bounded TCP connectivity probes to two fixed public infrastructure addresses. It sends no application payload, but those network endpoints can observe the source IP. The publication scanner permits only those reviewed literals in that specific module; operator endpoints are not permitted.
