#!/usr/bin/env sh

# SPDX-FileCopyrightText: 2026 BlueBell-XA
# SPDX-License-Identifier: GPL-3.0-or-later

set -eu

SERVICE_NAME="spoolman2klipper"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
SERVICE_USER=${SPOOLMAN2KLIPPER_USER:-${SUDO_USER:-$(id -un)}}
USER_HOME=$(getent passwd "${SERVICE_USER}" | cut -d: -f6)

if [ -z "${USER_HOME}" ]; then
    echo "Unable to determine home directory for user ${SERVICE_USER}" >&2
    exit 1
fi

PYTHON_BIN="${REPO_DIR}/venv/bin/python3"
SERVICE_SCRIPT="${REPO_DIR}/spoolman2klipper.py"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "Expected virtualenv Python not found: ${PYTHON_BIN}" >&2
    echo "Create it first with: python3 -m venv venv && venv/bin/pip3 install -r requirements.txt" >&2
    exit 1
fi

if [ ! -f "${SERVICE_SCRIPT}" ]; then
    echo "Service script not found: ${SERVICE_SCRIPT}" >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "This script writes ${SERVICE_PATH}; rerun it with sudo." >&2
    exit 1
fi

sed \
    -e "s#__SERVICE_USER__#${SERVICE_USER}#g" \
    -e "s#__REPO_DIR__#${REPO_DIR}#g" \
    -e "s#__PYTHON_BIN__#${PYTHON_BIN}#g" \
    -e "s#__SERVICE_SCRIPT__#${SERVICE_SCRIPT}#g" \
    "${REPO_DIR}/spoolman2klipper.service" > "${SERVICE_PATH}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "Installed and started ${SERVICE_NAME} for user ${SERVICE_USER}."
