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
    echo "The script will request sudo permissions when removing systemd service files." >&2
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

SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

# Determine sudo commands
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo "Error: sudo is required to remove systemd service, but was not found." >&2
        exit 1
    fi
fi

# 1. Stop, disable, and remove systemd service
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null || [ -f "${SERVICE_PATH}" ]; then
    echo "Stopping and disabling systemd service..."
    $SUDO systemctl stop "${SERVICE_NAME}" || true
    $SUDO systemctl disable "${SERVICE_NAME}" || true
fi

if [ -f "${SERVICE_PATH}" ]; then
    echo "Removing systemd service file..."
    $SUDO rm -f "${SERVICE_PATH}"
    $SUDO systemctl daemon-reload
fi

# 2. Remove virtualenv
if [ -d "${REPO_DIR}/venv" ]; then
    echo "Removing virtual environment at ${REPO_DIR}/venv..."
    rm -rf "${REPO_DIR}/venv"
fi

# 3. Remove configuration file from Klipper config directories
CONFIG_DIRS=$(find_klipper_config_dirs)
echo "${CONFIG_DIRS}" | while read -r config_dir; do
    if [ -n "${config_dir}" ]; then
        target_cfg="${config_dir}/spoolman2klipper.cfg"
        if [ -f "${target_cfg}" ]; then
            echo "Removing configuration file at ${target_cfg}..."
            rm -f "${target_cfg}"
        fi
    fi
done

echo "spoolman2klipper has been successfully uninstalled."

