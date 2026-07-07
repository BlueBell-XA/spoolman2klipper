#!/usr/bin/env sh

# SPDX-FileCopyrightText: 2026 BlueBell-XA
# SPDX-License-Identifier: GPL-3.0-or-later

set -eu

SERVICE_NAME="spoolman2klipper"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)

# Prevent running with sudo directly if a regular user invoked it
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
    echo "Error: Please run this script as a normal user, not with sudo/root." >&2
    echo "The script will request sudo permissions when installing systemd service files." >&2
    exit 1
fi

SERVICE_USER=${SPOOLMAN2KLIPPER_USER:-${SUDO_USER:-$(id -un)}}
USER_HOME=$(getent passwd "${SERVICE_USER}" | cut -d: -f6)

if [ -z "${USER_HOME}" ]; then
    echo "Unable to determine home directory for user ${SERVICE_USER}" >&2
    exit 1
fi

# Helper to find Klipper configuration directories (where printer.cfg/moonraker.conf are located)
find_klipper_config_dirs() {
    candidate_dirs=$(
        (
            for dir in "${USER_HOME}/printer_data/config" "${USER_HOME}/klipper_config"; do
                if [ -d "${dir}" ]; then
                    echo "${dir}"
                fi
            done
            find "${USER_HOME}" -maxdepth 3 \( -name "printer.cfg" -o -name "moonraker.conf" \) 2>/dev/null | while read -r file; do
                if [ -n "${file}" ]; then
                    dirname "${file}"
                fi
            done
        ) | sort -u | grep -v '^$'
    )

    if [ -z "${candidate_dirs}" ]; then
        echo "${USER_HOME}/printer_data/config"
    else
        echo "${candidate_dirs}"
    fi
}

PYTHON_BIN="${REPO_DIR}/venv/bin/python3"
SERVICE_SCRIPT="${REPO_DIR}/spoolman2klipper.py"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [ ! -f "${SERVICE_SCRIPT}" ]; then
    echo "Service script not found: ${SERVICE_SCRIPT}" >&2
    exit 1
fi

# 1. Create Python virtual environment and install dependencies
if [ ! -x "${PYTHON_BIN}" ]; then
    echo "Creating virtual environment at ${REPO_DIR}/venv..."
    python3 -m venv "${REPO_DIR}/venv"
fi
echo "Installing/updating dependencies..."
"${REPO_DIR}/venv/bin/pip" install --upgrade pip setuptools wheel
"${REPO_DIR}/venv/bin/pip" install -r "${REPO_DIR}/requirements.txt"

# 2. Copy configuration file to Klipper config directories
CONFIG_DIRS=$(find_klipper_config_dirs)
echo "${CONFIG_DIRS}" | while read -r config_dir; do
    if [ -n "${config_dir}" ]; then
        target_cfg="${config_dir}/spoolman2klipper.cfg"
        if [ ! -f "${target_cfg}" ]; then
            echo "Copying default configuration to ${target_cfg}..."
            mkdir -p "${config_dir}"
            cp "${REPO_DIR}/spoolman2klipper.cfg" "${target_cfg}"
        else
            echo "Configuration file already exists at ${target_cfg}, skipping copy."
        fi
    fi
done

# 3. Determine sudo commands to copy/enable service
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo "Error: sudo is required to install systemd service, but was not found." >&2
        exit 1
    fi
fi

TEMP_SERVICE=$(mktemp)
sed \
    -e "s#__SERVICE_USER__#${SERVICE_USER}#g" \
    -e "s#__REPO_DIR__#${REPO_DIR}#g" \
    -e "s#__PYTHON_BIN__#${PYTHON_BIN}#g" \
    -e "s#__SERVICE_SCRIPT__#${SERVICE_SCRIPT}#g" \
    "${REPO_DIR}/spoolman2klipper.service" > "${TEMP_SERVICE}"

echo "Installing systemd service to ${SERVICE_PATH}..."
$SUDO cp "${TEMP_SERVICE}" "${SERVICE_PATH}"
rm -f "${TEMP_SERVICE}"

echo "Enabling and starting systemd service..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable "${SERVICE_NAME}"
$SUDO systemctl restart "${SERVICE_NAME}"

echo "Installed and started ${SERVICE_NAME} successfully for user ${SERVICE_USER}."


