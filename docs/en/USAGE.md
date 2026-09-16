# Everyday use

[Русский](../ru/USAGE.md)

The current interface is primarily Russian. Commands are language-independent; natural-language English understanding depends on the optional model, which is currently prompted to answer in Russian.

| Command | Purpose |
|---|---|
| `/start`, `/help`, `/menu` | Open the home keyboard |
| `/status`, `/downloads` | Show managed downloads and disk availability |
| `/library` | Browse available managed media |
| `/about` | Show project information and configured image attribution |
| `/access` | Owner-only access list and recent denied attempts; contains personal IDs |

| Russian button/status | English meaning |
|---|---|
| Мои фильмы / Медиатека | My movies / library |
| Загрузки | Downloads |
| Найти фильм | Find a movie |
| Низкий / Средний / Высокий | Low / normal / high priority |
| Пауза / На паузе | Pause / paused |
| Начать / Продолжить | Start / resume |
| Удалить… | Delete… |
| Да, удалить файлы | Yes, delete files — destructive confirmation |
| Отмена | Cancel |
| Назад / Далее | Back / next |
| Готово / Загружается / Ошибка | Complete / downloading / error |
| ⏳ | A command is saved but not yet confirmed by the agent |

## Direct authorized download

Send a `.torrent` attachment (up to 2 MiB) or magnet URI in the private chat. It is treated as a movie download. The bot saves a job and later submits it to the Mac. A saved job is not proof that the transfer started. Watch `/downloads` for actual progress. The program does not verify licenses or the contents of the torrent; check these yourself first.

The progress estimate adapts to observed speed and can change sharply when peers or the disk slow down. Pause and priority commands may wait for connectivity. Do not repeatedly press buttons to fix an unavailable disk. A completed transfer still needs a successful library scan and playback test.

## Optional title search

When configured, type a title or description, choose a numbered candidate, and choose a season if requested. Film identity is distinct from a download source. The resolver can be wrong. After title selection, an eligible movie release may be queued automatically; configure only sources whose permitted use you understand. Otherwise select a listed release manually. With no indexer, identification can work but finding a downloadable release cannot.

## Deleting media

Open the library, select the exact item and inspect the confirmation. `Да, удалить файлы` deletes the selected managed files; `Отмена` cancels. Do not confirm while uncertain. Backups remain your responsibility. The application cannot recover deleted files for you.

## First-run acceptance

Verify authorized and unauthorized chat access, disk detection, one permitted small transfer, pause/resume, queue recovery after restarting the bot, library discovery, playback and deletion of that expendable test file. Use private state and your own test bot. Do not copy personal evidence into a public issue.

If the Mac is offline, check the agent terminal and optional SSH tunnel. If the disk is missing, check the mount path and UUID without creating substitute directories. If search fails, check provider configuration and quotas. Report only redacted errors and synthetic reproduction steps.
