# Public updates and discoverability

[Русский](../ru/PUBLICATION.md)

This project is maintained as a separate, generalized source distribution. It is not a mirror of a household's installation. Updates should describe reusable behavior, requirements, fixes and verified limitations; never publish an operator's device model/serial, account data, addresses, storage UUIDs, private conversations or deployment history.

## Checkpoints during assigned work

Create a local commit after a coherent feature, fix, refactor or documentation milestone in a user-assigned task. Record what changed, why and how it was checked. Keep unrelated work separate. Maintain a short changelog so a feature can be traced to its date and commit. Do not create empty commits, scheduled commits or unattended maintenance work.

A local commit is a checkpoint on the working machine; a push sends commits to GitHub; deployment changes a running installation. Report these separately. Local commits do not need a network connection or a complete history scan. Use checks proportionate to the change.

Before a public push, inspect the exact outgoing files and commits, verify the destination and run the publication checks. Removing a secret from today's file does not remove it from an older commit. Review the whole outgoing history before the first publication and new outgoing commits thereafter. The available `python3 scripts/check_public_tree.py --history` performs a full scan; it is a publication safeguard, not a periodic task or a requirement for every local commit. The operator's local pre-push guard runs only on push.

Review new manifest entries individually. Scanning does not recognize every possible secret, so content review remains required. Use synthetic examples and a collective commit identity with GitHub noreply. Never transfer private installation history. Remote CI does not connect to a private home server or deploy there. There is no recurring maintenance schedule.

## Finding the project

The English and Russian README pages state the actual purpose: a self-hosted Telegram assistant for a macOS media library using Transmission and optional Plex. The About description and topics describe those technologies and languages. Cross-linked installation, usage and architecture pages provide useful searchable text. Generic platform requirements do not describe a particular operator's device.

Search engines choose whether and when to crawl and index a public repository. Google explicitly states that meeting technical requirements does not guarantee indexing: [Google Search requirements](https://developers.google.com/search/docs/essentials/technical). Yandex describes its discovery and indexing process in [Yandex Webmaster](https://www.yandex.com/support/webmaster/en/yandex-indexing/site-indexing). This project does not promise rankings or use keyword stuffing, hidden piracy-oriented text, fake engagement or misleading labels. More commits alone do not establish useful new content.

The description must match the program. Do not market it as a way to obtain unauthorized media, bypass access controls or evade enforcement. The same truthful behavior and rights guidance apply in both languages. See [legal considerations](LEGAL.md); wording alone cannot remove legal exposure.
