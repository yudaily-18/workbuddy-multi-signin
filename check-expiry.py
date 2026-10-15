"""check-expiry.py - report token expiry for every captured account snapshot.

Usage (in auto-checkin\\workbuddy):
  python check-expiry.py            # offline: read expiresAt from each snapshot
  python check-expiry.py --live     # also call the checkin-status API per account
  python check-expiry.py --json     # machine-readable one line

Exit code: 0 = all healthy; 1 = at least one account SOON / EXPIRED / ERROR.
"SOON"  = token expires within 7 days -> re-login and re-capture before it dies.
WorkBuddy access tokens live ~28 days; the desktop client only refreshes the
LIVE login state, never a snapshot, so snapshots need a monthly re-capture.
"""

import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CREDS_DIR = os.path.join(HERE, "creds")
SIGNIN = os.path.join(HERE, "signin.py")
SOON_DAYS = 7


def _ms_to_dt(ms):
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def live_check(snapshot):
    """Run signin.py status against one snapshot; return (verdict, detail)."""
    env = dict(os.environ)
    env["WORKBUDDY_AUTH_FILE"] = snapshot
    try:
        p = subprocess.run([sys.executable, SIGNIN, "status"],
                           capture_output=True, timeout=120, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = p.stdout.decode("utf-8", "replace").strip().splitlines()
        if not out:
            return "ERROR", "no output (rc=%d)" % p.returncode
        data = json.loads(out[-1])

        # 形态 A：脚本带 result 字段的输出（鉴权失败 / silent 类结果）
        result = data.get("result")
        if result:
            if result in ("AUTH_REJECTED", "AUTH_ERROR", "NO_AUTH", "NO_SESSION"):
                return "EXPIRED", (data.get("report") or result)[:80]
            if result == "INACTIVE":
                return "INACTIVE", (data.get("report") or result)[:80]
            if result in ("CLAIMED", "ALREADY"):
                return "OK", (data.get("report") or result)[:80]
            return "ERROR", (data.get("report") or result)[:80]

        # 形态 B：`status` 命令的原始输出 {step, http, body}
        # 注意：这个形态没有 result 字段，早先版本误判成 ERROR，是解析 bug。
        http = data.get("http")
        body = data.get("body") or {}
        code = body.get("code")
        if http in (401, 403) or code in (401, 403):
            return "EXPIRED", "http=%s code=%s msg=%s" % (http, code, body.get("msg"))
        d = body.get("data") or {}
        if d.get("active") is False:
            return "INACTIVE", "账号在活动名单外（active=false）"
        if "today_checked_in" in d:
            return "OK", "active=%s 今日已签=%s 连签=%s 累计=%s" % (
                d.get("active"), d.get("today_checked_in"),
                d.get("streak_days"), d.get("total_credits"))
        return "ERROR", "未知返回体：%s" % json.dumps(body, ensure_ascii=False)[:80]
    except Exception as e:
        return "ERROR", str(e)[:80]


def main():
    live = "--live" in sys.argv
    as_json = "--json" in sys.argv

    snapshots = sorted(glob.glob(os.path.join(CREDS_DIR, "*.info")))
    rows = []
    for snap in snapshots:
        label = os.path.splitext(os.path.basename(snap))[0]
        try:
            with open(snap, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            rows.append({"label": label, "verdict": "ERROR", "detail": "unreadable: %s" % e})
            continue
        auth = d.get("auth") or {}
        uid = (d.get("account") or {}).get("uid")
        exp_dt = _ms_to_dt(auth.get("expiresAt"))
        ref_dt = _ms_to_dt(auth.get("refreshExpiresAt"))
        now = datetime.now(timezone.utc)
        if exp_dt:
            days = (exp_dt - now).days
            verdict = "EXPIRED" if days < 0 else ("SOON" if days <= SOON_DAYS else "OK")
            detail = "token expires %s (%d d)" % (exp_dt.astimezone().strftime("%Y-%m-%d %H:%M"), days)
            if ref_dt:
                detail += "; refresh %s" % ref_dt.astimezone().strftime("%Y-%m-%d")
        else:
            verdict, detail = "UNKNOWN", "no expiresAt in snapshot"
        row = {"label": label, "uid": uid, "verdict": verdict, "detail": detail}
        if live:
            lv, ld = live_check(snap)
            row["live"] = lv
            row["live_detail"] = ld
            # 只有实测到明确故障（401/异常）才改写静态 verdict；
            # INACTIVE 不覆盖——可能是活动未开，不代表 token 有问题。
            if lv in ("EXPIRED", "ERROR"):
                row["verdict"] = lv
        rows.append(row)

    # INACTIVE = 登录没问题、只是该账号不在签到活动名单里（等官方开活动），
    # 处理方式与"token 快过期"完全不同，不算需要续期的故障。
    healthy = ("OK", "INACTIVE")
    bad = [r for r in rows
           if r["verdict"] not in healthy or r.get("live") not in (None, "OK", "INACTIVE")]
    if as_json:
        print(json.dumps({"ok": not bad, "checked_at": datetime.now(timezone.utc).isoformat(),
                          "accounts": rows}, ensure_ascii=False))
    else:
        print("account snapshots in %s:" % CREDS_DIR)
        for r in rows:
            extra = " | live: %s" % r["live"] if r.get("live") else ""
            print("  %-22s %-8s %s%s" % (r["label"], r["verdict"], r["detail"], extra))
            if r.get("live"):
                print("  %-22s   -> [%s] %s" % ("", r["live"], r.get("live_detail") or ""))
        if bad:
            print("ACTION: re-login the flagged account(s) in the desktop client, then re-run")
            print("       python capture-account.py <label> --expect-phone <phone>")
        else:
            print("all snapshots healthy.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
