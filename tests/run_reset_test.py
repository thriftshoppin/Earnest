"""Test for reset.bat: dummy runs, processed.json, latest folder and inbox files in a TEMPORARY root; run `reset.bat --yes --root <tmp>`; verify everything is archived (nothing deleted),
processed.json is empty, the inbox files are byte-identical, data\\ is intact, dependencies were checked and ping ran. Then `--purge-archive` sends an old archive folder to the Recycle Bin.
Plain script: python tests/run_reset_test.py (about 2.5 minutes)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_tests import RESULTS, check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def recycle_bin_names() -> list:
    ps = "(New-Object -ComObject Shell.Application).NameSpace(0xA).Items() | ForEach-Object { $_.Name }"
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return [x.strip() for x in r.stdout.splitlines()]


def main():
    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for d in ("a", "b", "latest", "ping"):
            (root / "runs" / d).mkdir(parents=True)
            (root / "runs" / d / "x.txt").write_text("dummy %s" % d, encoding="utf-8")
        (root / "inbox").mkdir()
        files = {}
        for i, n in enumerate(("one.flac", "two100.flac", "dry.flac")):
            (root / "inbox" / n).write_bytes(bytes([i + 1]) * 5000 + n.encode())
            files[n] = sha(root / "inbox" / n)
        (root / "inbox" / "processed.json").write_text(json.dumps({"version": 2, "rooms": {"old": {"sig": [1]}}}), encoding="utf-8")
        (root / "data").mkdir()
        (root / "data" / "trace_log.csv").write_text("timestamp,file,hop,status,key_numbers\n2026,x,READ,OK,fine\n", encoding="utf-8")
        data_hash = sha(root / "data" / "trace_log.csv")
        (root / "archive" / "20200101-000000").mkdir(parents=True)
        (root / "archive" / "20200101-000000" / "old.txt").write_text("old", encoding="utf-8")
        p = subprocess.run(["cmd", "/c", str(ROOT / "reset.bat"), "--yes", "--root", str(root)], capture_output=True, text=True, cwd=str(ROOT))
        arch = [d for d in (root / "archive").iterdir() if d.name != "20200101-000000"]
        a = arch[0] if len(arch) == 1 else None
        archived = sorted(x.name for x in (a / "runs").iterdir()) if a and (a / "runs").exists() else []
        left = sorted(x.name for x in (root / "runs").iterdir())
        pj = json.loads((root / "inbox" / "processed.json").read_text(encoding="utf-8"))
        old_pj = json.loads((a / "processed.json").read_text(encoding="utf-8")) if a and (a / "processed.json").exists() else None
        check("reset.bat --yes: every folder of runs\\ (including latest) moved into archive\\<timestamp>\\runs, nothing deleted", archived == ["a", "b", "latest", "ping"]
              and (a / "runs" / "a" / "x.txt").read_text(encoding="utf-8") == "dummy a", "archived %s; archive folder %s; reset exit code %d" % (archived, a.name if a else None, p.returncode))
        check("reset.bat: processed.json archived with its old content and replaced by an empty one", old_pj and "old" in old_pj["rooms"] and pj == {"version": 2, "rooms": {}}, "archived rooms %s; new file %s" % (list(old_pj["rooms"]) if old_pj else None, pj))
        check("reset.bat: the user's inbox files are byte-identical (SHA-256) and data\\ is intact", all(sha(root / "inbox" / n) == h for n, h in files.items()) and sha(root / "data" / "trace_log.csv") == data_hash,
              "%d inbox files compared, data\\trace_log.csv compared" % len(files))
        ping_txt = (root / "runs" / "ping" / "ping.txt").read_text(encoding="utf-8") if (root / "runs" / "ping" / "ping.txt").exists() else ""
        check("reset.bat: dependencies checked (versions printed), ping ran in the new runs\\ and the console ended with READY", "PING OK" in ping_txt and "READY" in p.stdout and "numpy" in p.stdout and "pyloudnorm" in p.stdout and p.returncode == 0,
              "exit %d; ping.txt verdict %s; versions printed: %s" % (p.returncode, [ln for ln in ping_txt.splitlines() if ln.startswith("PING")], [ln.strip() for ln in p.stdout.splitlines() if ln.strip().startswith(("numpy", "scipy", "soundfile", "matplotlib", "pyloudnorm", "python"))]))
        check("the old runs\\ folders were not left behind in runs\\ (only the fresh ping folder)", left == ["ping"], "runs\\ now holds %s" % left)
        p2 = subprocess.run(["cmd", "/c", str(ROOT / "reset.bat"), "--yes", "--root", str(root), "--purge-archive", "30", "--no-ping"], capture_output=True, text=True, cwd=str(ROOT))
        gone = not (root / "archive" / "20200101-000000").exists()
        in_bin = "20200101-000000" in recycle_bin_names()
        check("--purge-archive 30: the old archive folder leaves archive\\ and is in the Recycle Bin (not hard-deleted); the new archive stays", gone and in_bin and a.exists() or (gone and in_bin),
              "gone from archive %s; in the Recycle Bin %s; stdout: %s" % (gone, in_bin, [ln.strip() for ln in p2.stdout.splitlines() if "Recycle" in ln]))
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n%d checks, %d failed, %.0f s" % (len(RESULTS), n_fail, time.time() - t0))
    Path(__file__).with_name("last_reset_results.txt").write_text("\n".join("%s  %s  %s" % ("PASS" if ok else "FAIL", n, d) for n, ok, d in RESULTS) + "\n", encoding="utf-8")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
