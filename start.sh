#!/bin/sh
# Launch Mogura using the project virtualenv if present, else system python.
if [ -x venv/bin/python ]; then
    exec venv/bin/python main.py
else
    exec python3 main.py
fi
