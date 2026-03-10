#!/bin/bash
python3 -m pip install -r requirements.txt --user
python3 -m pip install git+https://gitlab-ci-token:${CI_JOB_TOKEN}@code.stanford.edu/bil/user/kenjimar/2602_rig_public
python3 -m pip install git+https://gitlab-ci-token:${CI_JOB_TOKEN}@code.stanford.edu/bil/user/kenjimar/2601_boilerplate@scicd
