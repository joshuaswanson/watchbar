#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    /opt/homebrew/bin/python3.13 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

python3 app.py
