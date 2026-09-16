# Development checkpoints / Этапы разработки

Dates below describe changes to this source distribution, not a private installation. Local commits, GitHub publication and deployment are separate events.
Даты относятся к исходникам проекта, а не к частной установке. Локальный коммит, публикация и развёртывание — разные события.

## 2026-09-14 — Task-driven checkpoints / Фиксация порученной работы

Replaced the mistaken scheduled-maintenance workflow with commits at coherent milestones during assigned work. Added a discoverable development log. Kept privacy review before public pushes; removed the repeated full-history CI step. No runtime behavior changed.
Отменена ошибочная трактовка с расписанием: коммиты фиксируют законченные этапы порученной работы. Добавлен журнал разработки. Проверка приватности перед публичным push сохранена; повторная проверка всей истории в CI убрана. Поведение программы не менялось.

Find the checkpoint with / Найти коммит:
`git log --oneline --grep='Use task-driven checkpoints'`

## 2026-09-14 — Publication guard / Защита публикации

Commit: `749adf5`. Added source/history checks, guarded private paths and device identifiers, and EN/RU publication guidance. Validation: 292 tests passed. The original scheduled-maintenance interpretation in this checkpoint is superseded by the entry above.
Коммит: `749adf5`. Добавлены проверки состава/истории, запрет приватных путей и идентификаторов устройств, документация EN/RU. Проверка: 292 теста прошли. Первоначальная трактовка расписания отменена записью выше.

## 2026-09-14 — Initial public export / Первая публичная копия

Commit: `b908ce1`. Created a separate generalized source tree with EN/RU documentation, private configuration templates and numeric Telegram access. Validation: 288 tests passed. This checkpoint does not establish GitHub publication or deployment.
Коммит: `b908ce1`. Создана отдельная обобщённая копия с документацией EN/RU, шаблонами конфигурации и числовым доступом Telegram. Проверка: 288 тестов прошли. Запись не означает публикацию на GitHub или развёртывание.

## 2026-09-16 — current deployment reference

- Added a separate sanitized bot/Mac-agent source edition with bilingual single-Mac and split-host setup, generic service examples and a source hash manifest.
- Includes bounded search retries with visible attempt/reason updates, persistent film-specific retry buttons, click coalescing and partial results.
- Removed operator identities/configurations, captured search datasets and site-specific authenticated browser tooling from the export.
- Extended legal guidance for the United States, Russia and Europe without promising immunity or granting media rights.
- Validation: 292 baseline and 417 reference tests passed locally; CI now tests both editions. Publication/privacy checks include outgoing history. Identify this checkpoint with `git log -- deployment-reference/SNAPSHOT.md`; local checks and remote CI/publication are separate results.
