# Мониторинг отзывов LUDUS

Автоматически проверяет отзывы о клубе на **Google Maps** и **TripAdvisor** и шлёт
дайджест в Telegram-группу **5 раз в день** (09:00, 12:00, 15:00, 18:00, 20:00 по Пхукету).
На отзыв ниже 3★ — отдельный 🔴 аларм. Дашборд не нужен: всё в Telegram.

## Как работает

`GitHub Actions (cron 5×/день)` → `tools/сбор.py`:
Apify тянет отзывы Google + TripAdvisor → дедуп по ID (`данные/отзывы.json`) →
Telegram-дайджест (итоговые оценки с цветом + новые отзывы + ссылки) → коммит базы обратно.

Цвет в Telegram — кружками: 🟢 ≥4★ · 🟡 <4★ · 🔴 <3★.

## Файлы

- `tools/сбор.py` — сборщик + уведомления (весь движок).
- `tools/отзывы_проба.py`, `tools/telegram_проба.py` — пробы (для отладки).
- `.github/workflows/monitor.yml` — расписание 5×/день.
- `данные/отзывы.json` — база отзывов (состояние дедупликации, коммитится).
- `apify.config.json`, `telegram.config.json` — секреты для ЛОКАЛЬНОГО запуска (в `.gitignore`).

## Локальный запуск

```
python3 tools/сбор.py
```
Секреты берутся из `*.config.json`. Полезно для проверки перед деплоем.

## Деплой в GitHub (автозапуск 5×/день)

1. Создай **приватный** репозиторий (напр. `ludus-reviews`).
2. Залей в него файлы проекта: `tools/`, `.github/`, `данные/отзывы.json`, `.gitignore`, `README.md`.
   **Не заливай** `apify.config.json` и `telegram.config.json` — они с секретами (в `.gitignore`).
3. В репозитории: **Settings → Secrets and variables → Actions → New repository secret** — добавь 5 секретов:
   - `APIFY_TOKEN`
   - `GOOGLE_MAPS_URL`
   - `TRIPADVISOR_URLS` (если несколько — через запятую)
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Вкладка **Actions** → включи workflows, если попросит.
5. Открой workflow «Мониторинг отзывов LUDUS» → **Run workflow** (ручной запуск для проверки).
6. Дальше он сам запускается по расписанию. Секреты в коде не хранятся — только в GitHub Secrets.

Скрипт умеет брать секреты и из `*.config.json` (локально), и из переменных окружения
(в Actions) — один и тот же код работает и там, и там.
