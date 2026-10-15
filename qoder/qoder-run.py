"""qoder-run.py — Qoder 每日领取的无窗口启动器（替代 run_claim.bat）。

为什么要换掉 .bat：
  旧 run_claim.bat 用 python.exe（控制台程序）跑，会冒出黑窗口——
  每天 10:05 闪一次。这里改用 pythonw.exe + CREATE_NO_WINDOW，全程无窗口。

行为与旧 .bat 完全一致：设置 QODER_AUTH_DIR，把 --json 结果追加进 claim.log。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLAIM = os.path.join(HERE, "qoder_claim.py")
LOG = os.path.join(HERE, "claim.log")
# 与旧 run_claim.bat 里写死的路径保持一致（用 APPDATA 兜底）
AUTH_DIR = os.path.join(os.environ.get("APPDATA") or r"C:\Users\Administrator\AppData\Roaming",
                        "com.qodercn.app.stable")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main():
    env = os.environ.copy()
    env["QODER_AUTH_DIR"] = AUTH_DIR
    # 让 qoder_claim.py 用 UTF-8 输出，否则中文写进日志会变乱码
    env["PYTHONIOENCODING"] = "utf-8"

    with open(LOG, "a", encoding="utf-8") as f:
        p = subprocess.run(
            [sys.executable, CLAIM, "--base-url", "https://openapi.qoder.com.cn", "--json"],
            env=env, cwd=HERE, stdout=f, stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW, close_fds=True,
        )
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
