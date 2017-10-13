#!/bin/bash

set -e

for venv in virtualenv-3 virtualenv-3.5 virtualenv-3.6; do
  echo $venv
  if which $venv 2>/dev/null; then
    break
  fi
done


if [ ! "$venv" ]; then
  echo "Could not find virtual env 3"
  exit 1
fi

$venv env
env/bin/pip install -r requirements.txt
