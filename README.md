# Twitch -> Discord points bot (Python MVP)

Полный MVP для связки **Twitch + Discord**:

- пользователь нажимает кнопку в Discord и привязывает Twitch
- бот считает поинты во время стрима
- `+1 point` за минуту присутствия в Twitch chatters
- `+2 points` за минуту, если за эту минуту было хотя бы одно сообщение в чат
- бот постит эмбеды о начислениях и уровне в Discord
- бот выдает и обновляет роли по уровню

## 1. Что именно считает этот бот

Важно понимать ограничение Twitch API.

Этот проект считает не "идеальный просмотр видео", а **присутствие в Twitch-чате во время активного стрима**.
Причина простая: Twitch официально дает `Get Chatters`, а это список пользователей, подключенных к чату канала, а не гарантированный список всех фактических viewers.

То есть в рамках этого бота:

- **watch point** = пользователь найден в `Get Chatters`
- **message point** = пользователь написал хотя бы одно сообщение в течение минуты

## 2. Как это работает по архитектуре

Сервис состоит из двух частей, которые стартуют одним процессом:

1. **Discord bot**
   - отправляет панель привязки
   - обрабатывает кнопку `Привязать Twitch`
   - показывает `/progress`
   - шлет эмбеды в канал анонсов
   - выдает роли

2. **FastAPI web server**
   - принимает Twitch OAuth callback
   - принимает Twitch EventSub webhook
   - хранит связки и прогресс в SQLite

Во время стрима цикл идет по минутам:

1. приходит `stream.online`
2. бот включает минутный трекер
3. по `channel.chat.message` копятся авторы сообщений по минутам
4. раз в минуту вызывается `Get Chatters`
5. начисляются points
6. при апе уровня синкаются роли и шлется embed
7. приходит `stream.offline`
8. трекинг останавливается

## 3. Что тебе нужно заранее

Перед настройкой подготовь:

- сервер или ПК, где будет крутиться Python-процесс
- **Python 3.10+**
- **публичный HTTPS URL** для FastAPI
- Discord-сервер, где бот будет стоять
- Twitch-канал стримера
- желательно отдельный Twitch-аккаунт под бота или модератора

### Минимально рабочая схема аккаунтов

Есть 2 варианта:

### Вариант A. Нормальный

- **Twitch broadcaster account** = аккаунт стримера
- **Twitch bot/mod account** = отдельный аккаунт бота, который добавлен модератором на канал стримера

Это самый чистый и предсказуемый вариант.

### Вариант B. Один Twitch-аккаунт

Можно использовать аккаунт стримера и как `bot`, и как `broadcaster`.
Но тогда ты все равно должен пройти **обе** admin OAuth-настройки:

- `/admin/twitch/start/bot`
- `/admin/twitch/start/broadcaster`

Для MVP это может работать, но отдельный bot/mod аккаунт лучше.

## 4. Создание Discord-бота с нуля

### Шаг 1. Создай приложение

1. Открой Discord Developer Portal.
2. Нажми **New Application**.
3. Введи название.
4. Открой приложение.

### Шаг 2. Создай bot user

1. Зайди во вкладку **Bot**.
2. Нажми **Add Bot**.
3. Скопируй **Token**.
4. Сохрани его в `.env` как `DISCORD_TOKEN`.

### Шаг 3. Включи нужный privileged intent

Во вкладке **Bot** включи:

- **Server Members Intent**

Этот проект использует получение участника сервера и синк ролей, поэтому без `GUILD_MEMBERS` intent часть функций сломается.

### Шаг 4. Пригласи бота на сервер

Есть два варианта:

#### Вариант 1. Через OAuth2 URL Generator

1. Открой вкладку **OAuth2** -> **URL Generator**
2. В `Scopes` выбери:
   - `bot`
   - `applications.commands`
3. В `Bot Permissions` включи:
   - View Channels
   - Send Messages
   - Embed Links
   - Read Message History
   - Manage Roles
4. Сгенерируй invite URL
5. Открой ссылку и добавь бота на нужный сервер

#### Вариант 2. Собрать ссылку вручную

Подставь свой `APPLICATION_ID`:

```text
https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot%20applications.commands&permissions=268445760
```

Если хочешь, можешь не использовать готовое число permissions, а пригласить через URL Generator.

### Шаг 5. Проверь роль бота

На сервере Discord:

- роль бота должна быть **выше**, чем роли, которые он выдает
- у бота должно быть право **Manage Roles**
- канал привязки и канал анонсов должны быть доступны боту

### Шаг 6. Получи нужные Discord ID

Тебе понадобятся:

- `DISCORD_GUILD_ID`
- `DISCORD_BIND_CHANNEL_ID`
- `DISCORD_ANNOUNCE_CHANNEL_ID`
- ID ролей для `LEVEL_ROLE_MAP_JSON`

Самый простой способ:

1. В Discord включи **Developer Mode**
2. ПКМ по серверу / каналу / роли
3. Нажми **Copy ID**

## 5. Создание Twitch-приложения с нуля

### Шаг 1. Зарегистрируй приложение

1. Открой Twitch Developer Console.
2. Создай новое приложение.
3. В `Name` введи любое имя.
4. В `OAuth Redirect URLs` укажи callback URL.
   Он должен совпадать с `TWITCH_REDIRECT_URI`.
5. Выбери категорию приложения.
6. Сохрани приложение.

### Шаг 2. Получи Client ID и Client Secret

После создания приложения:

- скопируй `Client ID`
- создай и скопируй `Client Secret`

Запиши их в `.env`:

- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

### Шаг 3. Определи callback URL

Этот проект использует:

```text
GET /oauth/twitch/callback
```

Значит если твой домен:

```text
https://bot.example.com
```

то в Twitch app и `.env` должно быть:

```text
TWITCH_REDIRECT_URI=https://bot.example.com/oauth/twitch/callback
```

### Шаг 4. Подготовь bot/mod account

Если у тебя отдельный Twitch bot account:

1. создай отдельный Twitch-аккаунт
2. зайди на канал стримера
3. выдай ему модератора

Пример в Twitch-чате стримера:

```text
/mod имя_бота
```

Без этого `Get Chatters` обычно не пройдет как надо.

## 6. Зачем нужны две Twitch admin OAuth-настройки

В проекте есть **две отдельные системные привязки**:

### 1. `/admin/twitch/start/bot`

Используется для Twitch-аккаунта, который будет считаться `bot/mod` identity.

Нужен для:

- чтения чат-событий
- `Get Chatters`
- создания корректной связки для `channel.chat.message`

### 2. `/admin/twitch/start/broadcaster`

Используется для Twitch-аккаунта стримера.

Нужен для:

- подтверждения доступа к каналу стримера
- `channel:bot`
- корректной подписки EventSub на нужный канал

## 7. Обязательные Twitch scopes в этом проекте

По умолчанию в `.env.example` уже стоят:

```env
TWITCH_BOT_SCOPES=user:read:chat user:bot moderator:read:chatters
TWITCH_BROADCASTER_SCOPES=channel:bot
VIEWER_LINK_SCOPES=user:read:email
```

Что они означают:

- `user:read:chat` - читать чат-события
- `user:bot` - участвовать в chat/EventSub как bot user
- `moderator:read:chatters` - получать список chatters
- `channel:bot` - разрешение от broadcaster для работы chat bot-сценария
- `user:read:email` - опционально для viewer link flow; основной логике начисления email не нужен

## 8. Публичный HTTPS обязателен

Twitch EventSub webhook не будет нормально работать на обычном локальном `http://127.0.0.1:8080`.

Тебе нужен **публичный HTTPS endpoint**.

### В production

Нормально ставить так:

- приложение слушает `APP_HOST=0.0.0.0`, `APP_PORT=8080`
- спереди стоит Nginx / Caddy / reverse proxy
- наружу торчит HTTPS-домен

### Для локального теста

Проще всего использовать туннель, например:

- ngrok
- Cloudflare Tunnel
- другой публичный HTTPS tunnel

Пример логики для локального теста:

1. поднимаешь приложение локально на `localhost:8080`
2. запускаешь tunnel на `8080`
3. получаешь публичный URL, например:
   `https://abcd-12-34-56.ngrok-free.app`
4. ставишь его в:
   - `PUBLIC_BASE_URL`
   - `TWITCH_REDIRECT_URI`
5. этот же redirect URI прописываешь в Twitch app settings

## 9. Полная расшифровка `.env`

Скопируй `.env.example` в `.env`:

```bash
cp .env .env
```

Ниже пример с пояснениями.

```env
# =========================
# Discord
# =========================
DISCORD_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=123456789012345678
DISCORD_BIND_CHANNEL_ID=123456789012345678
DISCORD_ANNOUNCE_CHANNEL_ID=123456789012345678

# JSON map: level -> discord role id
# Пример: уровень 1 = роль A, уровень 5 = роль B, уровень 10 = роль C
LEVEL_ROLE_MAP_JSON={"1":123456789012345678,"5":223456789012345678,"10":323456789012345678}

# Сколько points нужно на 1 уровень
POINTS_PER_LEVEL=100

# true = писать embed о каждом начислении
# false = писать только level up embeds
ANNOUNCE_EVERY_GAIN=true

# =========================
# App / Web
# =========================
PUBLIC_BASE_URL=https://your-domain.example.com
APP_HOST=0.0.0.0
APP_PORT=8080
APP_SIGNING_SECRET=replace_with_a_long_random_secret

# Опционально. По умолчанию bot_data.sqlite3
DATABASE_PATH=bot_data.sqlite3

# =========================
# Twitch App
# =========================
TWITCH_CLIENT_ID=your_twitch_client_id
TWITCH_CLIENT_SECRET=your_twitch_client_secret
TWITCH_REDIRECT_URI=https://your-domain.example.com/oauth/twitch/callback
TWITCH_EVENTSUB_SECRET=replace_with_a_long_random_secret

# Viewer link flow
VIEWER_LINK_SCOPES=user:read:email

# Admin setup flows
TWITCH_BOT_SCOPES=user:read:chat user:bot moderator:read:chatters
TWITCH_BROADCASTER_SCOPES=channel:bot
```

### Что важно не перепутать

#### `PUBLIC_BASE_URL`

Только база сайта, без завершающего `/`:

```text
https://bot.example.com
```

#### `TWITCH_REDIRECT_URI`

Полный callback URL:

```text
https://bot.example.com/oauth/twitch/callback
```

#### `TWITCH_EVENTSUB_SECRET`

Любая длинная случайная строка.
Используется для проверки подписи webhook от Twitch.

#### `APP_SIGNING_SECRET`

Внутренний секрет приложения для `state` и внутренних защитных механизмов.
Тоже должен быть длинным и случайным.

#### `LEVEL_ROLE_MAP_JSON`

Пример:

```json
{"1":111111111111111111,"5":222222222222222222,"10":333333333333333333}
```

Поведение такое:

- на каждом обновлении берется **максимальная доступная роль** по текущему уровню
- остальные трекаемые level-роли снимаются

## 10. Установка проекта

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 11. Запуск проекта

```bash
python -m app.main
```

После старта процесс поднимает:

- Discord bot
- FastAPI server
- background minute loop

### Проверка, что сервер живой

Открой:

```text
GET /health
```

Должен вернуться JSON с `ok: true`.

## 12. One-time настройка Twitch после первого запуска

После того как проект уже доступен по `PUBLIC_BASE_URL`, нужно выполнить **две admin OAuth-настройки**.

### Шаг 1. Привяжи bot/mod Twitch identity

Открой в браузере:

```text
https://YOUR_PUBLIC_BASE_URL/admin/twitch/start/bot
```

Дальше:

1. войди в Twitch-аккаунт бота или модератора
2. подтверди scopes
3. дождись страницы `Bot auth saved`

### Шаг 2. Привяжи broadcaster Twitch identity

Открой:

```text
https://YOUR_PUBLIC_BASE_URL/admin/twitch/start/broadcaster
```

Дальше:

1. войди в Twitch-аккаунт стримера
2. подтверди scopes
3. дождись страницы `Broadcaster auth saved`

### Шаг 3. Проверь EventSub

После обеих OAuth-настроек проект автоматически пытается создать подписки на:

- `stream.online`
- `stream.offline`
- `channel.chat.message`

Если в callback странице написано, что `EventSub sync failed`, сначала проверяй:

- публично ли доступен `PUBLIC_BASE_URL`
- совпадает ли `TWITCH_REDIRECT_URI`
- правильно ли стоит `TWITCH_EVENTSUB_SECRET`
- действительно ли bot/mod аккаунт имеет нужные права

## 13. Отправка панели привязки в Discord

В Discord есть guild slash command:

```text
/send_bind_panel
```

Важно:

- команда доступна только в `DISCORD_GUILD_ID`
- команда помечена как `administrator only`
- панель уходит именно в `DISCORD_BIND_CHANNEL_ID`

После выполнения бот отправит embed с кнопкой:

```text
Привязать Twitch
```

## 14. Как пользователь привязывает Twitch

Flow для участника сервера:

1. пользователь нажимает кнопку `Привязать Twitch`
2. получает **ephemeral**-сообщение с персональной ссылкой
3. переходит на Twitch OAuth
4. авторизует Twitch-аккаунт
5. проект сохраняет связь:
   - `discord_user_id`
   - `twitch_user_id`
   - `twitch_login`
   - `twitch_display_name`

После этого начисления идут автоматически.

## 15. Как начисляются points

Каждую минуту, пока стрим онлайн:

- если Twitch user найден в `Get Chatters` -> `+1 watch point`
- если этот же user написал хотя бы одно сообщение за эту минуту -> `+2 message points`

Итог за минуту:

- только присутствует = `+1`
- присутствует и написал >=1 сообщение = `+3`
- спамит 20 сообщений за минуту = все равно `+3`

Это специально сделано так, чтобы не было тупого фарма спамом.

## 16. Как считается уровень

Уровень считается по формуле:

```text
level = total_points // POINTS_PER_LEVEL
```

Если:

```env
POINTS_PER_LEVEL=100
```

то:

- 0-99 points -> level 0
- 100-199 -> level 1
- 200-299 -> level 2
- и так далее

## 17. Какие команды есть у бота

### `/send_bind_panel`

Шлет панель привязки в `DISCORD_BIND_CHANNEL_ID`.

### `/progress`

Показывает пользователю:

- привязанный Twitch
- total points
- watch points
- message points
- level

## 18. Какие HTTP route есть в проекте

### Health

```text
GET /health
```

### Twitch OAuth callback

```text
GET /oauth/twitch/callback
```

### Twitch EventSub webhook

```text
POST /webhooks/twitch/eventsub
```

### Admin bot identity setup

```text
GET /admin/twitch/start/bot
```

### Admin broadcaster identity setup

```text
GET /admin/twitch/start/broadcaster
```

## 19. Первый нормальный smoke test

После полной настройки проверь так:

1. бот онлайн в Discord
2. `/send_bind_panel` отрабатывает
3. пользователь привязывает Twitch
4. стример запускает стрим
5. в Twitch-чате пользователь сидит в чате
6. пользователь пишет одно сообщение
7. через 1-2 минуты проверь:
   - `/progress`
   - embed в `DISCORD_ANNOUNCE_CHANNEL_ID`
   - наличие роли, если достигнут уровень

## 20. Частые проблемы и как чинить

### Проблема: slash commands не появились

Проверь:

- верный ли `DISCORD_GUILD_ID`
- установлен ли бот именно на этот сервер
- бот стартовал без ошибок
- у тебя есть права видеть команды приложения

Это guild commands, так что обычно они появляются быстро после старта.

### Проблема: `/send_bind_panel` пишет, что канал не текстовый

Проверь `DISCORD_BIND_CHANNEL_ID`.
Он должен указывать именно на обычный текстовый канал.

### Проблема: пользователь нажимает кнопку, но OAuth не открывается нормально

Проверь:

- `PUBLIC_BASE_URL`
- `TWITCH_REDIRECT_URI`
- доступен ли сайт снаружи
- совпадает ли redirect URI в Twitch app settings

### Проблема: после admin OAuth написано `EventSub sync failed`

Обычно виновато одно из этого:

- сайт не доступен по HTTPS снаружи
- неправильный `TWITCH_EVENTSUB_SECRET`
- неправильный callback URL
- bot/mod аккаунт не подходит под требования
- broadcaster flow не завершен

### Проблема: начисляется только `+2`, но не `+1`

Смотри `Get Chatters` цепочку:

- bot/mod token должен быть валиден
- у него должен быть `moderator:read:chatters`
- этот аккаунт должен быть **модератором у стримера** или самим стримером

### Проблема: сообщения не считаются

Проверь:

- bot setup flow прошел именно нужный Twitch-аккаунт
- broadcaster setup flow прошел именно стример
- EventSub подписка `channel.chat.message` реально создалась
- стрим действительно онлайн

### Проблема: роли не выдаются

Проверь:

- `Manage Roles`
- роль бота выше reward-ролей
- `LEVEL_ROLE_MAP_JSON` валиден
- ID ролей правильные
- пользователь есть на сервере

### Проблема: канал анонсов заспамлен

Поставь:

```env
ANNOUNCE_EVERY_GAIN=false
```

Тогда будут в основном level-up события, а не каждое начисление.

## 21. Локальный запуск через tunnel, если у тебя нет домена

Пример последовательности:

1. запускаешь проект:

```bash
python -m app.main
```

2. отдельно поднимаешь tunnel на `8080`
3. получаешь публичный HTTPS URL
4. обновляешь `.env`:

```env
PUBLIC_BASE_URL=https://your-tunnel.example
TWITCH_REDIRECT_URI=https://your-tunnel.example/oauth/twitch/callback
```

5. в Twitch app settings тоже меняешь redirect URI
6. перезапускаешь проект
7. заново проходишь admin setup flows

Если tunnel-URL меняется, OAuth и EventSub тоже придется перепривязывать.

## 22. Безопасность

Никогда не коммить в git:

- `.env`
- Discord bot token
- Twitch client secret
- Twitch user access tokens
- Twitch refresh tokens
- database file

Минимум добавь это в `.gitignore`:

```gitignore
.env
*.sqlite3
__pycache__/
.venv/
```

## 23. Полезные замечания по коду

- база по умолчанию: `bot_data.sqlite3`
- viewer link flow хранит связь Discord <-> Twitch
- при новом уровне бот снимает старые tracked level roles и оставляет максимальную подходящую
- кнопка работает только внутри сервера, не в DM

## 24. Короткий чеклист без воды

### Discord

- [ ] Создано приложение
- [ ] Создан bot user
- [ ] Включен Server Members Intent
- [ ] Бот приглашен с `bot` + `applications.commands`
- [ ] Есть права Send Messages, Embed Links, Manage Roles
- [ ] Роль бота выше reward-ролей
- [ ] Заполнены Guild ID и Channel ID

### Twitch

- [ ] Создано приложение в Twitch Developer Console
- [ ] Заполнены Client ID и Client Secret
- [ ] Redirect URI совпадает с `.env`
- [ ] Есть публичный HTTPS URL
- [ ] Bot/mod аккаунт существует и является модератором канала
- [ ] Пройден `/admin/twitch/start/bot`
- [ ] Пройден `/admin/twitch/start/broadcaster`

### App

- [ ] `.env` заполнен
- [ ] `python -m app.main` стартует без ошибок
- [ ] `/health` отвечает `ok: true`
- [ ] `/send_bind_panel` работает
- [ ] `/progress` работает

## 25. Официальные требования, на которые опирается этот проект

Ключевые внешние ограничения:

- Discord bot устанавливается через `bot` и `applications.commands`
- интерактивные кнопки используют `custom_id` и возвращают interaction
- `Server Members Intent` является privileged intent и включается в настройках приложения
- Twitch EventSub для webhook требует публичный HTTPS endpoint
- EventSub подписки создаются через app access token
- `Get Chatters` требует user access token со scope `moderator:read:chatters`
- user в этом токене должен быть модератором канала или самим broadcaster
- `channel.chat.message` при app access token требует `user:read:chat`, `user:bot` и либо `channel:bot`, либо moderator status

## 26. Если хочешь перевести MVP в production

Следующие логичные апгрейды:

- заменить SQLite на PostgreSQL
- добавить Alembic миграции
- вынести reverse proxy в Nginx/Caddy
- добавить structured logging
- добавить retry/backoff для Twitch API
- добавить admin commands для ручного ресинка ролей
- добавить web dashboard
- добавить rate limit и антидубль на announce embeds

---

## Официальная документация

Discord:

- https://docs.discord.com/developers/bots/overview
- https://docs.discord.com/developers/topics/oauth2
- https://docs.discord.com/developers/components/reference
- https://docs.discord.com/developers/interactions/receiving-and-responding
- https://docs.discord.com/developers/events/gateway
- https://docs.discord.com/developers/resources/guild

Twitch:

- https://dev.twitch.tv/docs/authentication/register-app
- https://dev.twitch.tv/docs/authentication/
- https://dev.twitch.tv/docs/authentication/scopes/
- https://dev.twitch.tv/docs/eventsub/
- https://dev.twitch.tv/docs/eventsub/handling-webhook-events
- https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/
- https://dev.twitch.tv/docs/chat/
- https://dev.twitch.tv/docs/chat/authenticating/
- https://dev.twitch.tv/docs/chat/irc-migration/
- https://dev.twitch.tv/docs/api/reference
