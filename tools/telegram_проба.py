#!/usr/bin/env python3
"""Проба Telegram-бота — узнать chat_id группы и отправить тестовое сообщение.

Два режима:
  python3 tools/telegram_проба.py --chatid   → показать chat_id доступных чатов
                                                (добавь бота в группу и напиши там что-нибудь)
  python3 tools/telegram_проба.py            → отправить тест в chat_id из конфига

Токен и chat_id — из telegram.config.json (в .gitignore). Только стдлиб Python 3.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)


def конфиг():
    for путь in (os.path.join(BASE, "telegram.config.json"),
                 os.path.join(ROOT, "telegram.config.json"),
                 os.path.join(os.getcwd(), "telegram.config.json")):
        if os.path.exists(путь):
            return json.load(open(путь, encoding="utf-8"))
    sys.exit("❌ Не найден telegram.config.json.")


def api(метод, params, token):
    url = f"https://api.telegram.org/bot{token}/{метод}"
    data = urllib.parse.urlencode(params).encode() if params else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": e.read().decode("utf-8", "ignore")[:200], "code": e.code}
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e.reason)}


def main():
    c = конфиг()
    token = (c.get("bot_token") or "").strip()
    if not token or token.startswith("ВСТАВЬ"):
        sys.exit("❌ В telegram.config.json не вписан bot_token (получи у @BotFather).")

    if "--chatid" in sys.argv:
        res = api("getUpdates", {}, token)
        if not res.get("ok"):
            sys.exit(f"❌ Ошибка: {res.get('error') or res}. Проверь токен.")
        чаты = {}
        for upd in res.get("result", []):
            for k in ("message", "edited_message", "channel_post", "my_chat_member"):
                if k in upd and "chat" in upd[k]:
                    ch = upd[k]["chat"]
                    чаты[ch["id"]] = f"{ch.get('type')} · {ch.get('title') or ch.get('username') or ch.get('first_name') or ''}"
        if not чаты:
            print("Пока пусто. Добавь бота в группу и НАПИШИ там любое сообщение, потом запусти снова.")
        else:
            print("Найденные чаты (id → что это):")
            for cid, оп in чаты.items():
                print(f"  chat_id = {cid}   ({оп})")
            print("\nДля группы бери отрицательный id (супергруппа начинается с -100…).")
        return

    chat_id = str(c.get("chat_id") or "").strip()
    if not chat_id or chat_id.startswith("ВСТАВЬ"):
        sys.exit("❌ chat_id не задан. Сначала: python3 tools/telegram_проба.py --chatid")
    res = api("sendMessage", {"chat_id": chat_id,
                              "text": "✅ Тест: бот «LUDUS · Отзывы» на связи."}, token)
    if res.get("ok"):
        print(f"✅ Отправлено в чат {chat_id}. Проверь Telegram-группу.")
    else:
        print(f"❌ Не отправилось: {res.get('error') or res}")


if __name__ == "__main__":
    main()
