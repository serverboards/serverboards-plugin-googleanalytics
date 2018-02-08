#!/bin/bash

set -e

pyvenv env
env/bin/pip install -r requirements.txt
