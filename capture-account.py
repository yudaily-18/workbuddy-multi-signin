"""capture-account.py — 把 WorkBuddy 客户端当前登录态抓取为多账号快照。

用法（在 auto-checkin\\workbuddy 目录下）：
  python capture-account.py <label> [--expect-phone <phone>] [--force]

做什么：
  1. 复制客户端当前登录态文件（%LOCALAPPDATA%\\...\\workbuddy-desktop.info）
     到 creds\\<label>.info（先写 .tmp 再原子替换，避免抓到写一半的文件）；
  2. 校验快照完整（有 accessToken、有 uid）；
  3. 解密 accessToken 解出 JWT，识别账号（手机号/昵称），写入 creds\\<label>.json；
  4. 防呆：抓到的账号跟 label 对不上、或跟已快照账号重复时，拒绝执行（--force 除外）。

注意：客户端同一时间只有一个登录态，切账号会覆盖它——所以抓取必须
在目标账号登录的状态下进行。抓完就可以切走，快照不受影响（解密密钥
是机器级的，不绑定账号，已实测）。

退出码：0 成功；1 参数/文件错误；2 抓到的账号与预期不符（未写入）；3 快照已存在且 uid 不同
"""

import argparse
import base64
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CREDS_DIR = os.path.join(HERE, "creds")
LIVE_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local"),
    "CodeBuddyExtension", "Data", "Public", "auth", "workbuddy-desktop.info",
)

# 可选的"主账号"防呆：把平时一直登录的那个账号填进下面的环境变量后，
# 若抓取时抓到的正好是它、而 label 又不是对应标签，说明很可能忘了切账号，脚本会拒绝写入。
#   WORKBUDDY_MAIN_UID   该账号的 uid
#   WORKBUDDY_MAIN_LABEL 该账号对应的标签
# 两项都留空则不启用这条检查（其余防呆照常生效）。
MAIN_UID = os.environ.get("WORKBUDDY_MAIN_UID", "")
MAIN_LABEL = os.environ.get("WORKBUDDY_MAIN_LABEL", "")


def _now_iso():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def _fail(msg, code=1):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(code)


def copy_with_retry(src, dst, attempts=4, delay=2.0):
    """客户端刷新 token 时会短时独占文件，拷贝可能撞 SharingViolation，重试即可。"""
    last = None
    for i in range(attempts):
        try:
            shutil.copyfile(src, dst)
            return
        except OSError as e:
            last = e
            if i < attempts - 1:
                time.sleep(delay)
    raise last


def identify(token_value):
    """返回 (uid_phone_or_None, nickname_or_None, token_kind)。优先解 JWT claims。"""
    kind = None
    token = None
    if isinstance(token_value, str):
        token, kind = token_value, "plaintext"
    else:
        import signin
        signin._started_at = time.monotonic()
        signin._budget_seconds = signin.DEFAULT_BUDGET_SECONDS
        try:
            runtime = signin.find_workbuddy_runtime()
            reply = signin._run_auth_helper(runtime, {"operation": "decrypt", "value": token_value})
            token, kind = reply.get("accessToken"), "sym-v1"
        except Exception as e:
            return None, None, "undecryptable:%s" % type(e).__name__
    if not token:
        return None, None, kind
    parts = token.split(".")
    if len(parts) != 3:
        return None, None, kind
    try:
        pad = lambda s: s + "=" * (-len(s) % 4)
        claims = json.loads(base64.urlsafe_b64decode(pad(parts[1])))
    except Exception:
        return None, None, kind
    who = claims.get("preferred_username") or claims.get("name") or claims.get("nickname")
    nick = claims.get("nickname") if claims.get("nickname") != who else None
    return who, nick, kind


def main():
    ap = argparse.ArgumentParser(description="capture WorkBuddy login state as a multi-account snapshot")
    ap.add_argument("label", nargs="?", default="", help="快照标签，如 account-a / account-b")
    ap.add_argument("--who", action="store_true", help="只报告客户端当前登录的账号，不写任何文件")
    ap.add_argument("--expect-phone", default="", help="预期手机号/登录名，不一致则拒绝")
    ap.add_argument("--force", action="store_true", help="跳过防呆检查")
    args = ap.parse_args()

    if args.who:
        # 只读模式：报告当前登录态是谁，供接单 AI 先验明正身
        if not os.path.isfile(LIVE_FILE):
            _fail("找不到客户端登录态文件：%s（客户端登录过吗？）" % LIVE_FILE)
        try:
            with open(LIVE_FILE, "r", encoding="utf-8") as f:
                live = json.load(f)
        except (OSError, ValueError) as e:
            _fail("登录态文件读不了：%s" % e)
        auth = live.get("auth") or {}
        account = live.get("account") or {}
        who, nick, kind = identify(auth.get("accessToken"))
        print(json.dumps({"ok": True, "mode": "who", "uid": account.get("uid"),
                          "who": who, "nickname": nick, "token_kind": kind}, ensure_ascii=False))
        sys.exit(0)

    if not args.label:
        _fail("缺少 label（或加 --who 只查当前登录账号）")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", args.label):
        _fail("label 含非法字符（只允许字母数字._-）")

    if not os.path.isfile(LIVE_FILE):
        _fail("找不到客户端登录态文件：%s（客户端登录过吗？）" % LIVE_FILE)

    os.makedirs(CREDS_DIR, exist_ok=True)
    dst = os.path.join(CREDS_DIR, args.label + ".info")
    tmp = dst + ".tmp"

    try:
        copy_with_retry(LIVE_FILE, tmp)
    except OSError as e:
        _fail("复制登录态失败：%s" % e)

    try:
        with open(tmp, "r", encoding="utf-8") as f:
            session = json.load(f)
    except (OSError, ValueError) as e:
        os.remove(tmp)
        _fail("快照不是合法 JSON（客户端正在改写？）：%s" % e)

    auth = session.get("auth") or {}
    account = session.get("account") or {}
    if not auth.get("accessToken") or not account.get("uid"):
        os.remove(tmp)
        _fail("快照缺少 accessToken 或 uid，客户端可能未完成登录")

    uid = account["uid"]
    who, nick, kind = identify(auth["accessToken"])

    # ---- 防呆检查 ----
    if not args.force:
        if MAIN_UID and uid == MAIN_UID and args.label != MAIN_LABEL:
            os.remove(tmp)
            _fail("抓到的是主账号 %s，不是目标账号——是不是忘了切账号？"
                  "如确需覆盖主账号快照，用 label=%s 或加 --force" % (MAIN_UID, MAIN_LABEL), 2)
        if os.path.isfile(dst):
            try:
                with open(dst, "r", encoding="utf-8") as f:
                    old = json.load(f)
                old_uid = (old.get("account") or {}).get("uid")
                if old_uid and old_uid != uid:
                    os.remove(tmp)
                    _fail("creds/%s.info 已存在且属于另一个账号（%s）。"
                          "确认要换成当前账号（%s）请加 --force" % (args.label, old_uid, uid), 3)
            except (OSError, ValueError):
                pass  # 旧快照损坏，直接覆盖
        if args.expect_phone and who and args.expect_phone not in str(who):
            os.remove(tmp)
            _fail("抓到的账号是 %s，与预期 %s 不符——登错号了？" % (who, args.expect_phone), 2)

    os.replace(tmp, dst)

    meta = {
        "label": args.label,
        "uid": uid,
        "uin": account.get("uin"),
        "who": who,
        "nickname": nick,
        "token_kind": kind,
        "endpoint": auth.get("endpoint") or "https://copilot.tencent.com",
        "captured_at": _now_iso(),
        "token_expires_at_ms": auth.get("expiresAt"),
        "refresh_expires_at_ms": auth.get("refreshExpiresAt"),
        "snapshot": dst,
    }
    meta_path = os.path.join(CREDS_DIR, args.label + ".json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(json.dumps({"ok": True, **meta}, ensure_ascii=False))


if __name__ == "__main__":
    main()
