# Dodo Pizza availability checker

Парсер проверяет, есть ли нужная пицца в меню Dodo Pizza для Москвы, и может
отправить отчет в Telegram.

## Как это работает

1. Скрипт открывает `https://dodopizza.ru/moscow`.
2. Достает ссылки вида `/moscow/product/...`.
3. Ищет пиццу по названию из `config.json` или по временному override.
4. Если обычный HTTP-запрос получает антибот-страницу, включается браузерный
   режим Playwright.

Для проверки по конкретным кафе в коде есть слой для внутренних эндпоинтов Dodo:
`/api/pizzerias` и `/api/{version}/menu/...`. В режиме `fetch_mode: "auto"`
запросы по кафе идут из браузерного контекста, а при сбое браузерного `fetch`
используется запасной путь через Playwright request context.

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item config.example.json config.json
python -m dodo_parser --config config.json
```

Разово проверить другую пиццу без правки конфига:

```powershell
python -m dodo_parser --config config.json --pizza-name "Пепперони"
```

Проверять каждые 10 минут:

```powershell
python -m dodo_parser --config config.json --interval 600
```

Запустить Telegram-бота:

```powershell
python -m dodo_parser --config config.json --bot
```

## Настройка

Главные поля в `config.json`:

```json
{
  "city": "moscow",
  "pizza_name": "Пепперони",
  "fetch_mode": "auto",
  "check_city_menu": true,
  "check_pizzerias": true,
  "show_missing_pizzerias": false
}
```

`pizza_name` используется как значение по умолчанию везде:

- при обычном запуске `python -m dodo_parser`
- при циклическом запуске с `--interval`
- в боте при команде `/check_pizza` без аргумента

`fetch_mode`:

- `auto`: сначала обычный HTTP, потом Playwright при антибот-челлендже.
- `http`: только обычный HTTP.
- `playwright`: сразу браузерный режим.

## Telegram

Создай бота через `@BotFather`, узнай `chat_id`, затем заполни:

```json
{
  "telegram_bot_token": "123:abc",
  "telegram_chat_id": "123456789"
}
```

Если поля пустые, отчет просто выводится в консоль.

В режиме `--bot` бот работает через long polling, поэтому на сервере не нужен
публичный HTTPS-адрес и webhook.

Бот выполняет проверку по явной команде, а в общем чате умеет принимать `@mention`
и затем ждать геопозицию Telegram.

Команды:

```text
/check_pizza
/check
```

Они проверяют пиццу из `config.json`, то есть текущее значение `pizza_name`.

Можно временно указать другое название:

```text
/check_pizza Пепперони
/check Мясная
```

Сценарий для общего чата:

```text
/check_pizza Пепперони
@your_bot где заказать
<отправить геопозицию Telegram следующим сообщением>
```

Бот запоминает последнюю искомую пиццу для чата, принимает следующую геопозицию
от того же пользователя, считает расстояния через routing API и показывает
первые 10 ближайших пиццерий, где эту пиццу можно заказать.

До отправки геопозиции обычный отчёт по команде `/check_pizza` показывает
общее количество найденных точек и только первые 5 адресов, чтобы не засорять чат.

Можно сразу указать другую пиццу через mention:

```text
@your_bot Маргарита
<отправить геопозицию Telegram следующим сообщением>
```

Команды `/start` и `/help` только показывают подсказку.

По умолчанию для расчёта расстояния используется OSRM-compatible routing API
по адресу `https://router.project-osrm.org`. При желании можно подставить свой
совместимый endpoint.

## Проверка по кафе

В Dodo наличие товара может зависеть от адреса или пиццерии. План такой:

1. Получить список пиццерий Москвы:
   `/api/pizzerias?localityId=0000002b-0000-0000-0000-000000000000`.
2. Для каждой пиццерии запросить меню:
   `/api/{version}/menu/{menu_type}/countries/RU/pizzerias/{pizzeriaId}?cultures=ru-RU&subcategoriesInMenu=false`.
3. Искать нужное название в JSON-ответе.

Если Dodo поменяет защиту или формат API, бот вернет понятную ошибку вместо
ложного списка.
