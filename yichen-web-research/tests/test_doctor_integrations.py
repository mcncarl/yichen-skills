#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
DOCTOR_PATH = ROOT / "yichen-web-research/scripts/doctor_yichen.py"
VALIDATOR_PATH = ROOT / "yichen-web-research/scripts/validate_family.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


doctor = load_module("test_doctor_yichen", DOCTOR_PATH)
validator = load_module("test_validate_family", VALIDATOR_PATH)


class StubPath:
    def __init__(self, value: str, *, present: bool, source: str = "") -> None:
        self.value = value
        self.present = present
        self.source = source

    def is_file(self) -> bool:
        return self.present

    def __str__(self) -> str:
        return self.value

    def __fspath__(self) -> str:
        return self.value

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.source


def completed(command: list[str], payload: object, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=command,
        returncode=0,
        stdout=json.dumps(payload),
        stderr=stderr,
    )


class ZhihuDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = StubPath(
            "/fixed/zhihu_adapter.py",
            present=True,
            source=(
                "subparsers = parser.add_subparsers()\n"
                "subparsers.add_parser('search')\n"
                "subparsers.add_parser('hot')\n"
            ),
        )
        self.cli = StubPath("/fixed/zhihu-cli", present=True)
        self.version = {
            "name": "zhihu-cli",
            "version": "0.0-test",
            "os": "darwin",
            "arch": "arm64",
        }
        self.capabilities = {
            "commands": [
                {"name": "search zhihu"},
                {"name": "search global"},
                {"name": "hot"},
                {"name": "answer"},
                {"name": "me contents"},
            ]
        }

    def invoke(self, auth: object, *, secret_stderr: str = ""):
        responses = [
            completed([str(self.cli), "version"], self.version, secret_stderr),
            completed(
                [str(self.cli), "capabilities"],
                self.capabilities,
                secret_stderr,
            ),
            completed(
                [str(self.cli), "auth", "status"],
                auth,
                secret_stderr,
            ),
        ]
        with (
            mock.patch.object(doctor, "ZHIHU_ADAPTER", self.adapter),
            mock.patch.object(doctor, "ZHIHU_CLI", self.cli),
            mock.patch.object(doctor.os, "access", return_value=True),
            mock.patch.object(doctor.subprocess, "run", side_effect=responses) as run,
            mock.patch.dict(
                os.environ,
                {
                    "PATH": "/usr/bin:/bin",
                    "ZHIHU_ACCESS_SECRET": "must-never-reach-the-child-or-report",  # pragma: allowlist secret
                    "OPENAI_API_KEY": "openai-secret",  # pragma: allowlist secret
                    "ANTHROPIC_API_KEY": "anthropic-secret",  # pragma: allowlist secret
                    "GITHUB_API_KEY": "github-secret",  # pragma: allowlist secret
                    "AWS_ACCESS_KEY_ID": "aws-secret",  # pragma: allowlist secret
                },
                clear=True,
            ),
        ):
            payload = doctor.zhihu_channel_status()
        return payload, run

    def test_ready_channel_uses_only_offline_metadata_and_keychain(self) -> None:
        payload, run = self.invoke(
            {
                "ok": True,
                "environment_set": False,
                "keychain": "found",
                "verification": "not_performed",
                "environment_shadows_keychain": False,
            },
            secret_stderr="stderr-secret-marker",  # pragma: allowlist secret
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["adapter_ready"])
        self.assertTrue(payload["cli_ready"])
        self.assertTrue(payload["auth_configured"])
        self.assertEqual(payload["credential_source"], "keychain")
        self.assertFalse(payload["network_probe_performed"])
        self.assertFalse(payload["default_backend"])
        self.assertTrue(payload["public_commands_only"])
        self.assertFalse(payload["personal_commands_exposed"])
        self.assertNotIn("stderr-secret-marker", json.dumps(payload))

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            commands,
            [
                [str(self.cli), "version"],
                [str(self.cli), "capabilities"],
                [str(self.cli), "auth", "status"],
            ],
        )
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"]["PATH"], "/usr/bin:/bin")
            for secret_name in (
                "ZHIHU_ACCESS_SECRET",
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "GITHUB_API_KEY",
                "AWS_ACCESS_KEY_ID",
            ):
                self.assertNotIn(secret_name, call.kwargs["env"])
            self.assertTrue(call.kwargs["capture_output"])
            self.assertIs(call.kwargs["stdin"], subprocess.DEVNULL)

    def test_available_keychain_requires_explicit_keychain_source(self) -> None:
        baseline = {
            "ok": True,
            "environment_set": False,
            "keychain": "available",
            "verification": "not_performed",
            "environment_shadows_keychain": False,
        }
        for source in (None, "environment", "config_file", "keychain"):
            with self.subTest(source=source):
                auth = dict(baseline)
                if source is not None:
                    auth["source"] = source
                payload, _ = self.invoke(auth)
                self.assertEqual(payload["status"], "ok" if source == "keychain" else "warn")
                self.assertEqual(payload["auth_configured"], source == "keychain")

    def test_missing_keychain_is_warn_not_structure_failure(self) -> None:
        payload, _ = self.invoke(
            {
                "ok": True,
                "environment_set": False,
                "keychain": "not_found",
                "verification": "not_performed",
                "environment_shadows_keychain": False,
            }
        )
        self.assertEqual(payload["status"], "warn")
        self.assertTrue(payload["adapter_ready"])
        self.assertTrue(payload["cli_ready"])
        self.assertFalse(payload["auth_configured"])
        self.assertIsNone(payload["credential_source"])

    def test_missing_cli_warns_without_running_any_command(self) -> None:
        missing_cli = StubPath("/fixed/zhihu-cli", present=False)
        with (
            mock.patch.object(doctor, "ZHIHU_ADAPTER", self.adapter),
            mock.patch.object(doctor, "ZHIHU_CLI", missing_cli),
            mock.patch.object(doctor.os, "access", return_value=False),
            mock.patch.object(doctor.subprocess, "run") as run,
        ):
            payload = doctor.zhihu_channel_status()
        run.assert_not_called()
        self.assertEqual(payload["status"], "warn")
        self.assertTrue(payload["adapter_ready"])
        self.assertFalse(payload["cli_ready"])

    def test_failed_metadata_never_exposes_stdout_stderr_or_secret(self) -> None:
        leak = "TOP-SECRET-MARKER"
        failed = subprocess.CompletedProcess(
            args=[str(self.cli), "version"],
            returncode=7,
            stdout=leak,
            stderr=leak,
        )
        with (
            mock.patch.object(doctor, "ZHIHU_ADAPTER", self.adapter),
            mock.patch.object(doctor, "ZHIHU_CLI", self.cli),
            mock.patch.object(doctor.os, "access", return_value=True),
            mock.patch.object(doctor.subprocess, "run", return_value=failed),
        ):
            payload = doctor.zhihu_channel_status()
        report = json.dumps(payload)
        self.assertEqual(payload["status"], "warn")
        self.assertNotIn(leak, report)
        self.assertNotIn("stdout", report)
        self.assertNotIn("stderr", report)

    def test_adapter_personal_command_is_detected_without_execution(self) -> None:
        unsafe_adapter = StubPath(
            "/fixed/zhihu_adapter.py",
            present=True,
            source=(
                "subparsers = parser.add_subparsers()\n"
                "subparsers.add_parser('search')\n"
                "subparsers.add_parser('hot')\n"
                "subparsers.add_parser('me contents')\n"
            ),
        )
        with (
            mock.patch.object(doctor, "ZHIHU_ADAPTER", unsafe_adapter),
            mock.patch.object(doctor, "ZHIHU_CLI", self.cli),
            mock.patch.object(doctor.os, "access", return_value=True),
            mock.patch.object(
                doctor.subprocess,
                "run",
                side_effect=[
                    completed([str(self.cli), "version"], self.version),
                    completed([str(self.cli), "capabilities"], self.capabilities),
                    completed(
                        [str(self.cli), "auth", "status"],
                        {
                            "ok": True,
                            "environment_set": False,
                            "keychain": "found",
                            "verification": "not_performed",
                            "environment_shadows_keychain": False,
                        },
                    ),
                ],
            ),
        ):
            payload = doctor.zhihu_channel_status()
        self.assertFalse(payload["adapter_ready"])
        self.assertFalse(payload["public_commands_only"])
        self.assertTrue(payload["personal_commands_exposed"])


class PortableIntegrationDoctorTests(unittest.TestCase):
    def test_stepfun_key_check_never_executes_the_configured_script(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"YICHEN_STEP_ASR_SCRIPT": "/untrusted/step_asr.py"},
            clear=True,
        ):
            self.assertFalse(doctor.stepfun_key_available())
        with mock.patch.dict(
            os.environ,
            {
                "YICHEN_STEP_ASR_SCRIPT": "/untrusted/step_asr.py",
                "STEPFUN_API_KEY": "present-but-not-read",  # pragma: allowlist secret
            },
            clear=True,
        ):
            self.assertTrue(doctor.stepfun_key_available())

    def test_firecrawl_private_file_check_reads_metadata_only(self) -> None:
        metadata = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=os.getuid(),
            st_size=32,
        )
        path = mock.Mock()
        path.lstat.return_value = metadata
        with (
            mock.patch.object(doctor, "FIRECRAWL_KEY_FILE", path),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(doctor.firecrawl_key_source(), "private_file")
        path.lstat.assert_called_once_with()
        path.read_text.assert_not_called()

    def test_firecrawl_rejects_overbroad_private_file_permissions(self) -> None:
        metadata = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o644,
            st_uid=os.getuid(),
            st_size=32,
        )
        path = mock.Mock()
        path.lstat.return_value = metadata
        with (
            mock.patch.object(doctor, "FIRECRAWL_KEY_FILE", path),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            self.assertIsNone(doctor.firecrawl_key_source())

    def test_codex_config_can_report_enabled_grok_plugin(self) -> None:
        config = StubPath(
            "/portable/config.toml",
            present=True,
            source=(
                '[plugins."grok-consult@personal"]\n'
                "enabled = true\n"
                '[plugins."other@bundle"]\n'
                "enabled = false\n"
            ),
        )
        with (
            mock.patch.object(doctor, "CODEX_CONFIG", config),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            self.assertTrue(doctor.grok_consult_enabled())

    def test_explicit_grok_enabled_override_takes_precedence(self) -> None:
        config = StubPath(
            "/portable/config.toml",
            present=True,
            source='[plugins."grok-consult@personal"]\nenabled = true\n',
        )
        with (
            mock.patch.object(doctor, "CODEX_CONFIG", config),
            mock.patch.dict(
                os.environ,
                {"YICHEN_GROK_CONSULT_ENABLED": "0"},
                clear=True,
            ),
        ):
            self.assertFalse(doctor.grok_consult_enabled())

    def test_family_doctor_allows_missing_zhihu_cli_and_key(self) -> None:
        payload = {
            "web": {
                "firecrawl": {
                    "configured": False,
                    "adapter_ready": True,
                    "credential_source": None,
                    "default_backend": False,
                    "network_probe_performed": False,
                }
            },
            "xiaohongshu": {
                "current_turn_authorization_required": False,
                "write_or_private_scope_authorization_required": True,
            },
            "douyin": {
                "current_turn_authorization_required": False,
                "write_or_private_scope_authorization_required": True,
            },
            "toutiao": {
                "login_required_for_search": False,
                "user_chrome_state_used": False,
                "video_results_included": False,
                "batch_search_allowed": False,
            },
            "x_bookmarks": {"status": "warn"},
            "twitter": {
                "active_backend": "official_cli_account_quota",
                "primary_login_required": True,
                "search_route": ["official_cli_account_quota", "fxtwitter-public"],
                "fxtwitter_fallback_condition": (
                    "explicit_account_quota_exhausted_only"
                ),
                "known_url_adapter_ready": True,
            },
            "asr": {"status": "warn", "billing_status": "unknown"},
            "zhihu": {
                "status": "warn",
                "adapter_ready": True,
                "cli_ready": False,
                "auth_configured": False,
                "credential_source": None,
                "network_probe_performed": False,
                "default_backend": False,
                "public_commands_only": True,
                "personal_commands_exposed": False,
            },
        }
        result = subprocess.CompletedProcess(
            args=["doctor"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )
        with mock.patch.object(validator, "run", return_value=result):
            report = validator.check_doctor()
        self.assertTrue(report["ok"])
        self.assertTrue(
            report["invariants"]["zhihu_cli_or_auth_missing_is_nonfatal"]
        )


if __name__ == "__main__":
    unittest.main()
