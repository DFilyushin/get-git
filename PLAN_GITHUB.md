# План: поддержка GitHub (аналог Get-Git для репозиториев GitHub)

> **Статус: реализовано в версии 2.0.0** с уточнением заказчика — вместо одного
> сервера введён мультиисточниковый подход: пользователь добавляет несколько
> источников (GitLab и/или GitHub), у каждого свои настройки, директория
> хранения кода и SSH-ключ. Настройки перенесены из config.json в SQLite-базу
> `%APPDATA%\GetGit\getgit.db`. Детали — в CHANGELOG.md (раздел 2.0.0).

## Вывод сразу

Отдельный инструмент писать не нужно: ~90% Get-Git (git-операции, зеркальная
синхронизация, UI, потоки, конфиг, keyring, сборка) от сервера не зависит.
Меняется только источник списка репозиториев. Правильная форма — **второй
API-клиент за общим интерфейсом провайдера** в этом же приложении.

## Чем GitHub отличается от GitLab

| Аспект | GitLab (сейчас) | GitHub |
|---|---|---|
| Базовый URL API | `https://<host>/api/v4` | `https://api.github.com`; для GitHub Enterprise Server — `https://<host>/api/v3` |
| Аутентификация | заголовок `PRIVATE-TOKEN` | `Authorization: Bearer <PAT>` + `Accept: application/vnd.github+json` + `X-GitHub-Api-Version: 2022-11-28` |
| Токен | PAT с правом `read_api` | classic PAT со scope `repo` (для приватных) либо fine-grained PAT с правами Metadata: Read + Contents: Read |
| Список репозиториев | `GET /projects?membership=true` | `GET /user/repos?per_page=100&affiliation=owner,collaborator,organization_member` |
| Пагинация | заголовок `X-Next-Page` | заголовок `Link` (`rel="next"`) |
| Идентификатор пути | `path_with_namespace` (вложенные подгруппы, N уровней) | `full_name` = `owner/repo` (всегда 2 уровня) |
| SSH URL | `ssh_url_to_repo` | `ssh_url` (`git@github.com:owner/repo.git`) |
| Ветка по умолчанию | `default_branch` | `default_branch` (то же имя поля) |
| Доступ к коду | роль Guest в приватном проекте не может клонировать → проверка `permissions`/`visibility` | если репозиторий виден в `/user/repos`, `permissions.pull` практически всегда `true` — аналога Guest нет, проверка вырождается в чтение `permissions.pull` |
| Лимиты API | практически не мешают | 5000 запросов/час с токеном; обрабатывать 403/429 и `X-RateLimit-Remaining` (для списка репозиториев запаса хватает с избытком) |
| Архивные | `archived=false` в запросе | фильтровать по полю `archived` в ответе |

Git-слой (`git_ops.py`) не меняется вообще: клонирование и зеркальная
синхронизация по SSH одинаковы, ключ добавляется в профиль GitHub так же,
как в GitLab.

## Изменения в коде

1. **Интерфейс провайдера** (`app/core/provider.py`):
   `RepoProvider` c единственным методом `list_projects() -> list[Project]`
   (и `check_token() -> str`). Существующий `Project` уже содержит всё
   необходимое (`path_with_namespace`, `ssh_url_to_repo`, `default_branch`,
   `can_download`) — менять его не нужно.
2. **`GitLabClient`** — привести к интерфейсу (фактически уже соответствует).
3. **`GitHubClient`** (`app/core/github_client.py`, ~80 строк):
   - заголовки `Authorization: Bearer`, `Accept`, `X-GitHub-Api-Version`;
   - `GET /user/repos` с пагинацией по `Link`;
   - маппинг: `full_name` → `path_with_namespace`, `ssh_url` → `ssh_url_to_repo`,
     `permissions.pull` → `can_download`, пропуск `archived`;
   - обработка 401/403/429 с понятными сообщениями (включая исчерпание rate limit).
4. **Конфиг**: поле `provider: "gitlab" | "github"` (+ `github_url` для
   Enterprise, по умолчанию `https://api.github.com`). Токены хранить под
   разными записями keyring (`GetGit-GitLab`, `GetGit-GitHub`).
5. **Настройки (UI)**: выпадающий список «Тип сервера» (GitLab / GitHub);
   подпись поля токена и подсказки меняются от выбора. `MainWindow`
   создаёт клиента через фабрику по конфигу — остальной UI без изменений.
6. **Тесты**: зеркальные тесты `GitHubClient` на моках (пагинация по `Link`,
   маппинг полей, 401, rate limit); интеграционные git-тесты общие и уже есть.

## Этапы и оценка

| # | Этап | Оценка |
|---|---|---|
| 1 | Интерфейс провайдера, рефакторинг GitLabClient | 0.5 дня |
| 2 | GitHubClient + тесты на моках | 1 день |
| 3 | Конфиг + выбор сервера в настройках, отдельные записи keyring | 0.5–1 день |
| 4 | Ручная проверка на github.com (личные + организационные приватные репо), сборка | 0.5–1 день |

Итого: **2.5–3.5 дня**. Версия с поддержкой обоих серверов — кандидат в 2.0.

## Риски и заметки

- **Fine-grained PAT и организации**: такие токены видят репозитории организации,
  только если организация их разрешила; в корпоративной среде надёжнее classic
  PAT со scope `repo` (или разрешение fine-grained токенов на уровне организации).
- **SAML SSO**: в организациях с SSO токен нужно «авторизовать» для организации
  (кнопка Configure SSO у токена), иначе приватные репо не видны — отразить
  в сообщении об ошибке и README.
- **Один инструмент — два сервера**: можно пойти дальше и позволить несколько
  профилей (GitLab + GitHub одновременно, каждый со своей директорией) — вне
  первой итерации.
