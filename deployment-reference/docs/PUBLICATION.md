# What is distributed and how to share the project

[Русский](PUBLICATION.ru.md) · [Operations](OPERATIONS.md) · [Legal sources](../../docs/en/LEGAL.md) · [Data flows](../../docs/en/PRIVACY.md)

Legal links checked on 16 September 2026. This is publication guidance and general information, not a legal assessment of a particular deployment. No wording can promise freedom from claims in the US, EU, Russia or elsewhere. Accurate documentation does not replace rights to code, artwork or content.

## Scope of distribution

The project connects an operator's Telegram bot, local agent, Transmission and optional media player. It distributes source, synthetic tests, empty templates and instructions. Readers install third-party applications separately and use their own accounts. Source publication does not provide access to a running household installation.

BitTorrent is described directly as data transfer that can include uploading to peers. Renaming it “cloud”, hiding its name or adding “educational use only” does not grant content rights. Documentation makes no promise of unrestricted access to films, immunity or anonymity.

## Decide per item

| Material | Inclusion condition |
|---|---|
| Original code/text | Distribution rights are held and applicable notices retained |
| Third-party code | Provenance/license established and conditions satisfied; otherwise omit |
| Configuration template | Dummy values without working credentials or infrastructure identifiers |
| Conversation example | Synthetic reproduction, not a personal-chat screenshot |
| Diagnostic output | Minimal manually reviewed, redacted excerpt |
| Third-party poster, logo or font | Omit without suitable rights and required attribution |
| Media, torrents or magnet catalogues | Unnecessary for this source publication; omit |
| Databases, backups, cookies, keys or populated server configs | Omit |

Public accessibility is not a free license. An API key permits access under that API's terms, not arbitrary redistribution. Even your own recording can contain third-party music, identifiable people or other separately protected material. Assess the particular object and use.

## Project license and dependencies

[MIT](../../LICENSE) covers original project material within contributors' rights. Preserve the copyright and license notice when required. It neither replaces component licenses nor licenses media. See [THIRD_PARTY_NOTICES](../../THIRD_PARTY_NOTICES.md). Check provenance for every added dependency or copied fragment; secret scanning does not perform that review. [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

## US, EU and personal use

The US Copyright Office explains that unauthorized downloading and uploading of protected works can infringe exclusive rights. Exceptions such as fair use depend on circumstances; “personal use” is not blanket permission. [Official FAQ](https://www.copyright.gov/help/faq/faq-fairuse.html).

The EU's ACI Adam judgment requires distinguishing lawful from unlawful sources for private copying. It does not provide blanket P2P sharing permission and is not a universal rule for every European country. Public distribution, data processing and offering a service require separate assessment. [Court summary](https://eur-lex.europa.eu/legal-content/EN/SUM/?uri=CELEX%3A62012CJ0435).

A GitHub repository, MIT license or complaint procedure does not prevent claims. GitHub processes notices under its [DMCA policy](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy). Do not describe this as a legally certified service. A jurisdiction-specific professional must assess particular activities. Additional sources, including Russian rules, appear in the [legal notes](../../docs/en/LEGAL.md).

## Personal data and support

User IDs, request history, filenames, network addresses, device details and account records can identify people. Enabled external providers receive relevant requests; the bot does not anonymize them. Do not promise complete confidentiality without examining actual data flows.

The GDPR exception for certain purely personal/household activities cannot automatically be applied to a public service. Where GDPR applies, assess legal basis, notice, retention, security, processors and international transfers. Absence of centralized installation telemetry does not remove an operator's responsibility to assess their processing. [GDPR Articles 2, 5, 6, 13 and Chapter V](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng).

Ask for synthetic issue reproductions, not whole databases or configuration files. Arrange a private channel before receiving sensitive details where necessary; a private channel does not justify collecting unnecessary data.

## Publication review

1. Assemble a separate public copy from selected files; never archive a running server wholesale.
2. Review the diff, new files, directory names, commit messages, author metadata, outgoing history and release archives.
3. Exclude credentials, real deployment addresses/IDs, private paths, databases, logs and media. Prefer synthetic examples over edited personal screenshots.
4. Establish provenance, license and notice requirements for new third-party material.
5. After committing locally, run `python3 scripts/check_public_tree.py --history` from the public root. This maintainer's private publication guard additionally checks destination and outgoing history. Passing checks is bounded evidence, not a universal guarantee.
6. After pushing, verify the published commit, file set and CI. Review release assets separately: a clean branch does not establish that an old ZIP is clean.

The GitHub owner remains visible. Publishing under your account is not anonymous; sanitization concerns private infrastructure and data, not hiding repository provenance. GitHub or readers may retain copies. If a key leaks, revoke it first, then clean the publication and contact platform support if necessary. Rewriting history alone cannot erase all copies.
