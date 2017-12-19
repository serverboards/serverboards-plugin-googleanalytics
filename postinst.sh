#!/bin/bash

set -e

virtualenv -p /usr/bin/python3 env
env/bin/pip install -r requirements.txt
