#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
# SPDX-FileCopyrightText: 2026 BlueBell-XA
# SPDX-License-Identifier: GPL-3.0-or-later

"""Synchronise active Spoolman filament data into Klipper macro variables."""

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set, Union
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from jsonrpc_websocket import Server
import toml


PROGNAME = "spoolman2klipper"
CFG_DIR = "~/.config/" + PROGNAME
CFG_FILE = PROGNAME + ".cfg"
DEFAULT_KLIPPER_MACRO = "SPOOLMAN"

SPOOL_VARS_DEFAULT: Dict[str, Any] = {
    "spool_id": -1,
    "filament_name": "",
    "material": "",
    "vendor": "",
    "color": "",
    "extruder_temp": 0,
    "bed_temp": 0,
    "diameter": 0.0,
    "density": 0.0,
    "remaining_weight": 0.0,
    "filament_weight": 0.0,
}


class Spoolman2Klipper:  # pylint: disable=too-many-instance-attributes
    """Moonraker agent that exposes active Spoolman data to Klipper macros."""

    def __init__(self, config: Dict[str, Any]):
        service_config = config[PROGNAME]
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.moonraker_server: Optional[Server] = None
        self.moonraker_url = service_config["moonraker_url"].rstrip("/")
        self.spoolman_url = service_config["spoolman_url"].rstrip("/")
        self.spoolman_ws_url = self.build_spoolman_websocket_url(self.spoolman_url)
        self.klipper_macro = service_config.get(
            "klipper_macro", DEFAULT_KLIPPER_MACRO
        )
        self.sync_on_connect = service_config.get("sync_on_connect", True)
        self.reconnect_delay = float(service_config.get("reconnect_delay", 2.0))
        self.request_timeout = float(service_config.get("request_timeout", 5.0))
        self.server_factory = Server
        self.is_closing = False
        self.macro_variables: Optional[Set[str]] = None
        self.active_spool_id: Optional[Union[int, str]] = None
        self.active_spool_data: Optional[Dict[str, Any]] = None

    def extract_spool_variables(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten the Spoolman spool payload into Klipper macro variables."""

        filament: Dict[str, Any] = data.get("filament") or {}
        vendor = filament.get("vendor") or {}
        if not isinstance(vendor, dict):
            vendor = {}

        return {
            "spool_id": data.get("id", SPOOL_VARS_DEFAULT["spool_id"]),
            "filament_name": filament.get("name")
            or SPOOL_VARS_DEFAULT["filament_name"],
            "material": filament.get("material") or SPOOL_VARS_DEFAULT["material"],
            "vendor": vendor.get("name") or SPOOL_VARS_DEFAULT["vendor"],
            "color": filament.get("color_hex") or SPOOL_VARS_DEFAULT["color"],
            "extruder_temp": filament.get("settings_extruder_temp")
            or SPOOL_VARS_DEFAULT["extruder_temp"],
            "bed_temp": filament.get("settings_bed_temp")
            or SPOOL_VARS_DEFAULT["bed_temp"],
            "diameter": filament.get("diameter") or SPOOL_VARS_DEFAULT["diameter"],
            "density": filament.get("density") or SPOOL_VARS_DEFAULT["density"],
            "remaining_weight": data.get("remaining_weight")
            or SPOOL_VARS_DEFAULT["remaining_weight"],
            "filament_weight": filament.get("weight")
            or SPOOL_VARS_DEFAULT["filament_weight"],
        }

    def format_set_variable_gcode(self, variable_name: str, value: Any) -> str:
        """Build a SET_GCODE_VARIABLE command for one Klipper macro variable."""

        if isinstance(value, str):
            safe_value = self._sanitise_gcode_string(value)
            formatted_value = f"\"'{safe_value}'\""
        else:
            formatted_value = str(value)

        return (
            f"SET_GCODE_VARIABLE MACRO={self.klipper_macro} "
            f"VARIABLE={variable_name} VALUE={formatted_value}"
        )

    async def push_klipper_variables(self, variables: Dict[str, Any]) -> None:
        """Push supported variables into Klipper, skipping undefined variables."""

        if self.moonraker_server is None:
            return
        if self.macro_variables is None:
            await self.detect_macro_variables()
            if self.macro_variables is None:
                return

        for variable_name, value in variables.items():
            if variable_name not in self.macro_variables:
                continue

            script = self.format_set_variable_gcode(variable_name, value)
            try:
                await self._run_gcode(script)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.warning(
                    "Failed to update Klipper variable %s: %s",
                    variable_name,
                    exc,
                )

    async def notify_active_spool_set(self, params: Dict[str, Any]) -> None:
        """Handle Moonraker's active spool notification payload."""

        spool_id = params.get("spool_id")
        self.active_spool_id = spool_id
        if spool_id is None:
            self.active_spool_data = None
            await self.push_klipper_variables(SPOOL_VARS_DEFAULT)
            return

        spool_data = await self.fetch_spool_info(spool_id)
        if spool_data is None:
            logging.info("Spool ID %s not found, clearing Klipper variables", spool_id)
            self.active_spool_data = None
            await self.push_klipper_variables(SPOOL_VARS_DEFAULT)
            return

        if isinstance(spool_data, Exception):
            logging.info(
                "Attempt to fetch Spoolman data for spool %s failed: %s",
                spool_id,
                spool_data,
            )
            return

        self.active_spool_data = spool_data
        await self.push_klipper_variables(self.extract_spool_variables(spool_data))

    async def fetch_spool_info(
        self, spool_id: Union[int, str]
    ) -> Optional[Union[Dict[str, Any], Exception]]:
        """Fetch one spool from the configured Spoolman HTTP API."""

        if self.http_session is None:
            raise RuntimeError("HTTP session is not initialised")

        try:
            async with self.http_session.get(
                f"{self.spoolman_url}/v1/spool/{spool_id}",
                timeout=self.request_timeout,
            ) as response:
                if response.status == 404:
                    return None
                if response.status == 200:
                    return await response.json()
                return Exception(await response.text())
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            return exc

    async def handle_spoolman_event(self, event: Dict[str, Any]) -> None:
        """Handle one event from Spoolman's spool websocket."""

        if event.get("resource") != "spool":
            return

        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return

        spool_id = payload.get("id")
        if spool_id != self.active_spool_id:
            return

        event_type = event.get("type")
        if event_type == "updated":
            self.active_spool_data = payload
            await self.push_klipper_variables(self.extract_spool_variables(payload))
        elif event_type == "deleted":
            self.active_spool_id = None
            self.active_spool_data = None
            await self.push_klipper_variables(SPOOL_VARS_DEFAULT)

    async def handle_klippy_ready(self, *_args: Any, **_kwargs: Any) -> None:
        """Refresh macro state after Klipper becomes ready."""

        await self.detect_macro_variables()
        if self.active_spool_data is not None:
            await self.push_klipper_variables(
                self.extract_spool_variables(self.active_spool_data)
            )
            return
        if self.sync_on_connect:
            await self.sync_current_active_spool()

    async def handle_klippy_disconnected(self, *_args: Any, **_kwargs: Any) -> None:
        """Clear cached macro metadata after Klipper disconnects or shuts down."""

        self.macro_variables = None

    async def detect_macro_variables(self) -> None:
        """Detect the configured Klipper macro and its available variables."""

        if self.moonraker_server is None:
            self.macro_variables = None
            return

        objects = await self.moonraker_server.printer.objects.list()
        macro_key = f"gcode_macro {self.klipper_macro}"
        if macro_key not in objects.get("objects", []):
            logging.info("Klipper macro %s was not found", self.klipper_macro)
            self.macro_variables = None
            return

        try:
            result = await self.moonraker_server.printer.objects.query(
                objects={macro_key: None}
            )
            status = result.get("status", result)
            macro_state = status.get(macro_key, {})
            self.macro_variables = set(macro_state.keys())
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning(
                "Detected macro %s but could not query variables: %s",
                self.klipper_macro,
                exc,
            )
            self.macro_variables = None

    async def sync_current_active_spool(self) -> None:
        """Optionally pull Moonraker's current active spool on service startup."""

        if self.moonraker_server is None:
            return

        try:
            response = await self.moonraker_server.server.spoolman.spool_id()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning("Unable to query current Moonraker active spool: %s", exc)
            return

        spool_id = self.parse_spool_id_response(response)
        await self.notify_active_spool_set({"spool_id": spool_id})

    async def _run_gcode(self, script: str) -> None:
        """Run one G-code script through Moonraker."""

        logging.info("Run in Klipper: %s", script)
        await self.moonraker_server.printer.gcode.script(  # type: ignore[union-attr]
            script=script,
            _notification=True,
        )

    async def moonraker_connection_loop(self, max_cycles: Optional[int] = None) -> None:
        """Reconnect to Moonraker whenever the websocket receive loop exits."""

        cycles = 0
        while not self.is_closing:
            if max_cycles is not None and cycles >= max_cycles:
                return
            cycles += 1
            try:
                await self.moonraker_connection_cycle()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.warning("Moonraker connection cycle failed: %s", exc)
            finally:
                self.moonraker_server = None
                self.macro_variables = None

            if not self.is_closing and (
                max_cycles is None or cycles < max_cycles
            ):
                await asyncio.sleep(self.reconnect_delay)

    async def moonraker_connection_cycle(self) -> None:
        """Run one Moonraker websocket connection until it closes."""

        self.moonraker_server = self.server_factory(self.moonraker_url)
        receive_task = None
        try:
            receive_task = await self.moonraker_server.ws_connect()
            await self.detect_macro_variables()
            self.register_moonraker_notification_handlers()

            if self.sync_on_connect:
                await self.sync_current_active_spool()

            await receive_task
        finally:
            if receive_task is not None and not receive_task.done():
                receive_task.cancel()
            await self.moonraker_server.close()

    def register_moonraker_notification_handlers(self) -> None:
        """Register notification callbacks used by Moonraker and Klipper events."""

        if self.moonraker_server is None:
            return
        self.moonraker_server.notify_active_spool_set = self.notify_active_spool_set
        self.moonraker_server.notify_klippy_ready = self.handle_klippy_ready
        self.moonraker_server.notify_klippy_shutdown = self.handle_klippy_disconnected
        self.moonraker_server.notify_klippy_disconnected = (
            self.handle_klippy_disconnected
        )

    async def spoolman_connection_loop(self) -> None:
        """Reconnect to Spoolman's websocket whenever it exits."""

        while not self.is_closing:
            try:
                await self.spoolman_connection_cycle()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.warning("Spoolman websocket cycle failed: %s", exc)

            if not self.is_closing:
                await asyncio.sleep(self.reconnect_delay)

    async def spoolman_connection_cycle(self) -> None:
        """Read one Spoolman websocket connection until it closes."""

        if self.http_session is None:
            raise RuntimeError("HTTP session is not initialised")

        async with self.http_session.ws_connect(
            self.spoolman_ws_url,
            heartbeat=20,
            timeout=self.request_timeout,
        ) as websocket:
            async for message in websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    try:
                        await self.handle_spoolman_event(json.loads(message.data))
                    except (TypeError, json.JSONDecodeError) as exc:
                        logging.debug("Ignored invalid Spoolman websocket event: %s", exc)
                elif message.type == aiohttp.WSMsgType.ERROR:
                    raise aiohttp.ClientError("Spoolman websocket error")

    async def _routine(self) -> None:
        async with aiohttp.ClientSession() as self.http_session:
            moonraker_task = asyncio.create_task(self.moonraker_connection_loop())
            spoolman_task = asyncio.create_task(self.spoolman_connection_loop())
            try:
                await asyncio.gather(moonraker_task, spoolman_task)
            finally:
                self.is_closing = True
                for task in (moonraker_task, spoolman_task):
                    if not task.done():
                        task.cancel()

    def run(self) -> None:
        """Run the long-lived service in the default async event loop."""

        asyncio.get_event_loop().run_until_complete(self._routine())

    @staticmethod
    def parse_spool_id_response(response: Dict[str, Any]) -> Optional[Union[int, str]]:
        """Extract Moonraker's active spool ID from known response shapes."""

        if "spool_id" in response:
            return response.get("spool_id")

        result = response.get("result")
        if isinstance(result, dict):
            return result.get("spool_id")

        return None

    @staticmethod
    def build_spoolman_websocket_url(spoolman_url: str) -> str:
        """Build Spoolman's spool websocket URL from the configured API URL."""

        parts = urlsplit(spoolman_url.rstrip("/"))
        scheme = "wss" if parts.scheme == "https" else "ws"
        path = parts.path.rstrip("/") + "/v1/spool"
        return urlunsplit((scheme, parts.netloc, path, "", ""))

    @staticmethod
    def _sanitise_gcode_string(value: str) -> str:
        """Keep macro string values on one line and remove quote delimiters."""

        return (
            value.replace("'", "")
            .replace('"', "")
            .replace("\n", " ")
            .replace("\r", " ")
        )


def load_config() -> Optional[Dict[str, Any]]:
    """Load user configuration from the supported config locations."""

    for path in ["~/" + CFG_FILE, CFG_DIR + "/" + CFG_FILE]:
        cfg_filename = os.path.expanduser(path)
        if os.path.exists(cfg_filename):
            with open(cfg_filename, "r", encoding="utf-8") as file_pointer:
                return toml.load(file_pointer)
    return None


def install_default_config() -> None:
    """Copy the repo default config to the user's config directory."""

    cfg_dir = os.path.expanduser(CFG_DIR)
    Path(cfg_dir).mkdir(parents=True, exist_ok=True)

    script_dir = os.path.dirname(__file__)
    from_filename = os.path.join(script_dir, CFG_FILE)
    to_filename = os.path.join(cfg_dir, CFG_FILE)
    shutil.copyfile(from_filename, to_filename)
    print(f"Created {to_filename}, please update it", file=sys.stderr)


if __name__ == "__main__":
    logging.basicConfig(encoding="utf-8", level=logging.INFO)
    config_data = load_config()
    if not config_data:
        print(
            "WARNING: The configuration file is missing, installing a default version.",
            file=sys.stderr,
        )
        install_default_config()
        sys.exit(1)

    spoolman2klipper = Spoolman2Klipper(config_data)
    spoolman2klipper.run()
