#!/usr/bin/env python3
# ============================================================
# МОСТ «Герман <-> телефон» (Termux)
# ------------------------------------------------------------
# Скрипт опрашивает воркер Германа (очередь команд в KV) и
# выполняет команды на твоём телефоне. Результат уходит обратно
# в Telegram-чат.
#
# ЗАПУСК В TERMUX (одна команда):
#   curl -sL -o ~/bridge.py https://raw.githubusercontent.com/ildus650-pixel/orda__ii/main/herman/termux-bridge.py
#   BRIDGE_KEY='твой_ключ' python ~/bridge.py
#
# ИСПОЛЬЗОВАНИЕ:
#   Напиши боту:  Телефон: echo привет
#   или:          Телефон: termux-notification --title Тест --content Привет
#   (termux-notification доступен после: pkg install termux-api)
#
# БЕЗОПАСНОСТЬ:
#   - BRIDGE_KEY — это пароль доступа к твоему телефону. Не свети.
#   - ALLOWED = [] означает «разрешены все команды» (доверенный канал).
#     Можно ограничить, например: ALLOWED = ['echo', 'termux-notification']
# ============================================================

import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = 'https://herman.orda-ai.workers.dev'
# Ключ берётся из окружения (или аргумента) — в файле его нет
BRIDGE_KEY = os.environ.get('BRIDGE_KEY') or (sys.argv[1] if len(sys.argv) > 1 else '')
if not BRIDGE_KEY:
    print('Укажи ключ: BRIDGE_KEY=... python ~/bridge.py')
    sys.exit(1)
POLL_SECONDS = 5

# Пустой список = все команды разрешены
ALLOWED = []

BASH = '/data/data/com.termux/files/usr/bin/bash'


def api(path, data=None):
    url = BASE + path
    headers = {'Authorization': 'Bearer ' + BRIDGE_KEY}
    if data is not None:
        req = urllib.request.Request(
            url, data=json.dumps(data).encode('utf-8'),
            headers={**headers, 'Content-Type': 'application/json'}, method='POST')
    else:
        req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def allowed(cmd):
    if not ALLOWED:
        return True
    return any(cmd.strip().startswith(a) for a in ALLOWED)


def main():
    print('Мост запущен. Жду команды от Германа... (Ctrl+C — выход)')
    while True:
        try:
            nxt = api('/bridge/next')
            if nxt.get('command'):
                cmd = nxt['command']
                cid = nxt.get('id', '')
                if not allowed(cmd):
                    api('/bridge/done', {'id': cid, 'ok': False,
                                         'output': 'Команда не в белом списке: ' + cmd})
                    continue
                print('Выполняю:', cmd)
                try:
                    p = subprocess.run([BASH, '-c', cmd], capture_output=True,
                                       text=True, timeout=180)
                    out = (p.stdout or '') + (('\n' + p.stderr) if p.stderr else '')
                    api('/bridge/done', {'id': cid, 'ok': p.returncode == 0,
                                         'output': (out or '(нет вывода)')[-1500:]})
                except subprocess.TimeoutExpired:
                    api('/bridge/done', {'id': cid, 'ok': False, 'output': 'Таймаут команды'})
        except Exception as e:
            print('Ошибка:', e)
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
