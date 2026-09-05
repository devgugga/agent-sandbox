"""Testes de cli/asb/install.py — instaladores do host."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import install  # noqa: E402


class TestInstallGuards(unittest.TestCase):
    def test_guards_creates_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            fake_root = Path(tmp) / "checkout"
            guard_bin = fake_root / "cli" / "asb-guard"
            guard_bin.parent.mkdir(parents=True)
            guard_bin.write_text("#!/bin/sh\n")

            with mock.patch.object(Path, "home", return_value=fake_home):
                code = install.guards(fake_root)

            self.assertEqual(code, 0)
            local_bin = fake_home / ".local" / "bin"
            for agent in ("claude", "codex", "agy"):
                link = local_bin / f"asb-{agent}"
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), guard_bin.resolve())

    def test_guards_instala_o_proprio_asb_agent_no_path(self):
        """O CLI precisa rodar de qualquer diretorio, nao so do checkout.

        Ele ja funciona por symlink — Path(__file__).resolve() segue o link —
        entao o que faltava era so instalar o link.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            fake_root = Path(tmp) / "checkout"
            (fake_root / "cli").mkdir(parents=True)
            (fake_root / "cli" / "asb-guard").write_text("#!/bin/sh\n")
            cli = fake_root / "cli" / "asb-agent"
            cli.write_text("#!/usr/bin/env python3\n")

            with mock.patch.object(Path, "home", return_value=fake_home):
                code = install.guards(fake_root)

            self.assertEqual(code, 0)
            link = fake_home / ".local" / "bin" / "asb-agent"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), cli.resolve())

    def test_guards_substitui_asb_agent_de_checkout_antigo(self):
        """Modo de falha da §16.1: a pasta muda de lugar e o link fica orfao."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            fake_root = Path(tmp) / "checkout"
            (fake_root / "cli").mkdir(parents=True)
            (fake_root / "cli" / "asb-guard").write_text("#!/bin/sh\n")
            cli = fake_root / "cli" / "asb-agent"
            cli.write_text("#!/usr/bin/env python3\n")

            local_bin = fake_home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            (local_bin / "asb-agent").symlink_to(Path(tmp) / "checkout-velho"
                                                 / "cli" / "asb-agent")

            with mock.patch.object(Path, "home", return_value=fake_home):
                install.guards(fake_root)

            self.assertEqual((local_bin / "asb-agent").resolve(), cli.resolve())

    def test_guards_is_idempotent_and_replaces_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            fake_root = Path(tmp) / "checkout"
            guard_bin = fake_root / "cli" / "asb-guard"
            guard_bin.parent.mkdir(parents=True)
            guard_bin.write_text("#!/bin/sh\n")

            local_bin = fake_home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            # Existing regular file
            (local_bin / "asb-claude").write_text("old file")
            # Existing broken symlink
            (local_bin / "asb-codex").symlink_to(Path(tmp) / "nonexistent")

            with mock.patch.object(Path, "home", return_value=fake_home):
                code = install.guards(fake_root)

            self.assertEqual(code, 0)
            for agent in ("claude", "codex", "agy"):
                link = local_bin / f"asb-{agent}"
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), guard_bin.resolve())
