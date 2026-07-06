# encoding=utf-8

import os
import csv
import datetime as d
import pandas as pd

class csvtool(object):
    def __init__(self, dir):
        self.dir = dir
        # Do not create any files up front
        os.makedirs(self.dir, exist_ok=True)
        self.curDir = os.path.join(self.dir, self.curDate())
        os.makedirs(self.curDir, exist_ok=True)
        # Track which output files already have a header written (per process)
        self._header_written = set()

    def curDate(self):
        return d.datetime.now().strftime('%Y-%m-%d')

    def curFileName(self):
        return d.datetime.now().strftime('%Y%m%d.csv')

    def _resolve_path(self, isFinalResult: bool) -> str:
        # Ensure today's folder exists; roll over at midnight
        newDir = os.path.join(self.dir, self.curDate())
        if newDir != self.curDir:
            self.curDir = newDir
        os.makedirs(self.curDir, exist_ok=True)

        name = ('finalresult_' + self.curFileName()) if isFinalResult else self.curFileName()
        return os.path.join(self.curDir, name)

    def _pending_path(self, out_path: str) -> str:
        return out_path + ".pending"

    def _need_header(self, out_path: str) -> bool:
        if out_path in self._header_written:
            return False
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return False
        return True

    def _append_direct(self, out_path: str, rows, need_header: bool):
        header = ["game", "idx", "class_dealer", "class_model", "score", "card_number", "endid"]
        with open(out_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if need_header:
                writer.writerow(header)
            writer.writerows(rows)
        if need_header:
            self._header_written.add(out_path)

    def _queue_pending(self, out_path: str, rows):
        pending = self._pending_path(out_path)
        with open(pending, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)

    def _flush_pending(self, out_path: str) -> int:
        pending = self._pending_path(out_path)
        if not os.path.exists(pending) or os.path.getsize(pending) <= 0:
            return 0

        with open(pending, "r", newline="", encoding="utf-8") as f:
            rows = [row for row in csv.reader(f) if row]
        if not rows:
            try:
                os.remove(pending)
            except OSError:
                pass
            return 0

        # If Excel is locking out_path, _append_direct raises and the pending
        # file is kept for the next retry.
        self._append_direct(out_path, rows, self._need_header(out_path))
        try:
            os.remove(pending)
        except OSError:
            pass
        return len(rows)

    def _safe_append_rows(self, out_path: str, rows):
        try:
            self._flush_pending(out_path)
            self._append_direct(out_path, rows, self._need_header(out_path))
            return True
        except (PermissionError, OSError) as e:
            # Windows Excel commonly locks CSV files. Queue the rows instead of
            # crashing/stalling pydealerclient. They will be merged on a later write.
            try:
                self._queue_pending(out_path, rows)
                print("[csvtool] CSV locked/unavailable; queued rows to %s. error=%s" % (self._pending_path(out_path), e))
            except Exception as qe:
                print("[csvtool] failed to write CSV and failed to queue pending rows. csv=%s error=%s queue_error=%s" % (out_path, e, qe))
            return False

    def write(self, messagelist, isFinalResult):
        # ✅ No rows -> do nothing (prevents empty files)
        if not messagelist:
            return

        out_path = self._resolve_path(isFinalResult)
        rows = list(messagelist)  # shallow copy; don't mutate caller data
        self._safe_append_rows(out_path, rows)

csvtooler = csvtool('./csv')

def tocsv(message, isFinalResult):
    csvtooler.write(message, isFinalResult)
