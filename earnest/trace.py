"""Traceroute-style telemetry: every stage (hop) of a pipeline reports what it received against what it expected, as OK / WARN / FAIL with the numbers.

    tr = Trace("union100.flac")
    with tr.hop("READ") as h:
        ...
        h.ok("2 ch, peak -0.0 dBFS", peak=...)        # or h.warn(...) / h.fail(reason, cause)
    tr.finish(run_dir)                                  # prints the table, writes trace.txt and trace.json, appends data\\trace_log.csv

The first FAIL hop raises HopFail, which the caller catches: that file's pipeline stops, the trace so far is kept, and the next file goes on.
A hop that runs over WATCHDOG_S seconds is a FAIL ("stuck at hop X"); Ctrl+C prints every active trace."""
from __future__ import annotations

import csv
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .io import ROOT, save_json

WATCHDOG_S = 600.0
LOG_DEFAULT = ROOT / "data" / "trace_log.csv"      # EARNEST_TRACE_LOG overrides it (the tests use a temporary file)
ACTIVE: list = []          # traces that have not been finished (printed by Ctrl+C)


def _live(msg):
    """One timestamped line per hop start/end, flushed at once, so a console always shows what the code is doing (EARNEST_LIVE=0 turns it off)."""
    if os.environ.get("EARNEST_LIVE", "1") != "0":
        print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


class HopFail(Exception):
    def __init__(self, hop, reason, cause=""):
        super().__init__("%s: %s" % (hop, reason))
        self.hop, self.reason, self.cause = hop, reason, cause


def _short(v):
    if isinstance(v, float):
        return "%.2f" % v
    return str(v)


class Hop:
    def __init__(self, trace, name):
        self.trace, self.name, self.status, self.msg, self.data, self.cause = trace, name, None, "", {}, ""
        self.t0 = 0.0
        self._timer = None

    def __enter__(self):
        self.t0 = time.time()
        _live("%s  %-8s started" % (self.trace.label, self.name))
        self._timer = threading.Timer(self.trace.watchdog_s, self._stuck)
        self._timer.daemon = True
        self._timer.start()
        return self

    def _stuck(self):
        self.status, self.msg = "FAIL", "stuck at hop %s: no result after %.0f s" % (self.name, self.trace.watchdog_s)
        self.cause = "a very large or damaged file, or a stalled disk"
        self.trace._record(self)
        self.trace.failed = True
        print(self.trace.render(), flush=True)
        try:
            self.trace.finish(self.trace.out_dir, quiet=True)
        finally:
            os._exit(3)

    def ok(self, msg="", **data):
        self.status, self.msg, self.data = "OK", msg, data

    def warn(self, msg, **data):
        self.status, self.msg, self.data = "WARN", msg, data

    def fail(self, reason, cause="", **data):
        self.status, self.msg, self.cause, self.data = "FAIL", reason, cause, data
        raise HopFail(self.name, reason, cause)

    def __exit__(self, et, ev, tb):
        if self._timer:
            self._timer.cancel()
        if et is not None and not issubclass(et, HopFail):
            if issubclass(et, KeyboardInterrupt):
                self.status, self.msg = "FAIL", "interrupted (Ctrl+C)"
                self.trace._record(self)
                self.trace.failed = True
                return False
            self.status, self.msg, self.cause = "FAIL", "%s: %s" % (et.__name__, ev), "an unexpected error inside this hop (see the message)"
            self.trace._record(self)
            self.trace.failed = True
            raise HopFail(self.name, self.msg, self.cause) from ev
        if self.status is None:
            self.status = "OK"
        self.trace._record(self)
        if self.status == "FAIL":
            self.trace.failed = True
        return False


class Trace:
    def __init__(self, label, watchdog_s=WATCHDOG_S, log=True):
        self.label, self.hops, self.failed, self.watchdog_s, self.log = str(label), [], False, watchdog_s, log
        self.out_dir = None
        self.t0 = time.time()
        self.closed = False
        ACTIVE.append(self)

    def hop(self, name):
        return Hop(self, name)

    def _record(self, h: Hop):
        _live("%s  %-8s %-4s %5.1f s  %s" % (self.label, h.name, h.status, time.time() - h.t0, h.msg))
        self.hops.append({"hop": h.name, "status": h.status, "msg": h.msg, "cause": h.cause, "data": h.data, "seconds": round(time.time() - h.t0, 2),
                          "at": datetime.now().strftime("%H:%M:%S")})

    def add(self, name, status, msg, **data):
        """Records a hop that needs no context manager (summary hops)."""
        self.hops.append({"hop": name, "status": status, "msg": msg, "cause": "", "data": data, "seconds": 0.0, "at": datetime.now().strftime("%H:%M:%S")})
        if status == "FAIL":
            self.failed = True

    def extend(self, other: "Trace", prefix: str = ""):
        for h in other.hops:
            self.hops.append({**h, "hop": prefix + h["hop"]})
        self.failed = self.failed or other.failed

    @property
    def status(self):
        s = [h["status"] for h in self.hops]
        return "FAIL" if "FAIL" in s else ("WARN" if "WARN" in s else "OK")

    def render(self) -> str:
        w = max([len(h["hop"]) for h in self.hops] + [4])
        L = ["TRACE %s" % self.label, "%-*s  %-4s  %s" % (w, "HOP", "STAT", "WHAT IT RECEIVED (against what was expected)")]
        for h in self.hops:
            L.append("%-*s  %-4s  %s" % (w, h["hop"], h["status"], h["msg"]))
            if h["status"] == "FAIL" and h.get("cause"):
                L.append("%-*s        most likely cause: %s" % (w, "", h["cause"]))
        fails = [h for h in self.hops if h["status"] == "FAIL"]
        L.append("RESULT: %s%s" % (self.status, ("  (stopped at %s)" % fails[0]["hop"]) if fails else ""))
        return "\n".join(L)

    def finish(self, out_dir=None, quiet=False, name="trace"):
        """Prints the table (unless quiet), writes trace.txt / trace.json into out_dir and appends every hop to data\\trace_log.csv."""
        if self.closed:
            return
        self.closed = True
        if self in ACTIVE:
            ACTIVE.remove(self)
        text = self.render()
        if not quiet:
            print(text, flush=True)
        if out_dir:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / (name + ".txt")).write_text(text + "\n", encoding="utf-8")
            save_json(out / (name + ".json"), {"label": self.label, "status": self.status, "hops": self.hops})
        if self.log:
            LOG = Path(os.environ.get("EARNEST_TRACE_LOG", LOG_DEFAULT))
            try:
                LOG.parent.mkdir(parents=True, exist_ok=True)
                new = not LOG.exists()
                with open(LOG, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(["timestamp", "file", "hop", "status", "key_numbers"])
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    for h in self.hops:
                        w.writerow([now, self.label, h["hop"], h["status"], (h["msg"] + (" | " + json.dumps(h["data"], default=_short) if h["data"] else ""))[:500]])
            except OSError:
                pass            # a locked log must not stop the analysis


def print_active():
    """Called on Ctrl+C: prints every unfinished trace."""
    for t in list(ACTIVE):
        print("\n(interrupted) " + t.render(), flush=True)
        try:
            t.finish(t.out_dir, quiet=True)
        except Exception:
            pass
