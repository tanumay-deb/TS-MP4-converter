"""Self-update: the command must really run setup and relaunch the app (Windows only)."""
import os
import subprocess
import time

import pytest

import app

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows self-update")


def test_update_command_runs_setup_and_relaunches(tmp_path):
    # As a list, cmd got the quotes escaped as \": setup never ran and the relaunch
    # failed with "Windows cannot find '\\'". Paths have spaces, like Program Files.
    d = tmp_path / "dir with spaces"
    d.mkdir()
    setup = d / "fake setup.bat"
    setup.write_text('@echo off\necho %* > "%~dp0setup-ran.txt"\n')
    relaunch = d / "fake app.vbs"                   # a GUI host: no console window pops up
    relaunch.write_text('Set f = CreateObject("Scripting.FileSystemObject")\n'
                        'f.CreateTextFile(f.GetParentFolderName(WScript.ScriptFullName)'
                        ' & "\\relaunched.txt").Close\n')
    subprocess.Popen(app.updater_cmdline(setup, relaunch, wait=0), creationflags=0x08000000)
    ran, relaunched = d / "setup-ran.txt", d / "relaunched.txt"
    deadline = time.time() + 15
    while time.time() < deadline and not (ran.exists() and relaunched.exists()):
        time.sleep(0.2)
    assert ran.exists() and "/SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS" in ran.read_text()
    assert relaunched.exists()
