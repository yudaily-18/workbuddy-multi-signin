"""run-account.py — 计划任务用的无窗口启动器（替代 run-account.bat）。

用法（由计划任务调用）:
  pythonw.exe run-account.py <label> <mode>
  mode: silent（每日签到+成长） 或 silent-poll（补签+成长）

为什么要换掉 .bat：
  Windows 执行 .bat 会创建一个 cmd.exe 控制台窗口——每 4 小时闪一次黑框很烦。
  pythonw.exe 是 GUI 子系统程序，启动时不创建控制台，所以全程无窗口。

行为与旧 .bat 完全一致：设置 WORKBUDDY_AUTH_FILE / WORKBUDDY_SIGNIN_LOG，
快照不存在时记 MISSING_SNAPSHOT 并返回 4，否则同步等待 signin.py 跑完并透传退出码。
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CREDS = os.path.join(HERE, "creds")
SIGNIN = os.path.join(HERE, "signin.py")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _append_log(path, text):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def main():
    if len(sys.argv) < 2:
        return 3
    label = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "silent"

    auth = os.path.join(CREDS, label + ".info")
    log = os.path.join(CREDS, label + ".log")

    if not os.path.isfile(auth):
        _append_log(log, "MISSING_SNAPSHOT %s (run capture-account.py first)" % auth)
        return 4

    env = os.environ.copy()
    env["WORKBUDDY_AUTH_FILE"] = auth
    env["WORKBUDDY_SIGNIN_LOG"] = log

    # sys.executable 在 pythonw 下就是 pythonw.exe，子进程同样无窗口
    p = subprocess.run(
        [sys.executable, SIGNIN, mode],
        env=env, cwd=HERE, creationflags=NO_WINDOW, close_fds=True,
    )
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
