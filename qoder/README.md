# Qoder 部分

让 Qoder 的「每日 100 Credits」在 Windows 上无人值守领取。

和 WorkBuddy 那套一样的目标：**挂到系统计划任务里，之后不用管**。

---

## 文件

| 文件 | 来源 | 说明 |
|---|---|---|
| `qoder_claim.py` | [sunp-1/qoder-checkin](https://github.com/sunp-1/qoder-checkin)（MIT） | 领取主程序，**原样收录，未做任何改动** |
| `qoder-run.py` | 本项目 | 计划任务启动器（无窗口、结果落日志） |

## 为什么还要一个启动器

上游脚本的设计是「不写任何文件，结果只走 stdout」—— 这对手工跑或被 Qoder 自带的自动化面板调用很合适，但挂到 Windows 计划任务上有两个小问题：

1. 直接执行 `.bat` 或 `python.exe` 会**闪出控制台窗口**；
   `qoder-run.py` 用 pythonw 配合 `CREATE_NO_WINDOW` 启动，全程无窗口。
2. 上游刻意不落盘，事后不好查账；
   启动器负责把结果追加到同目录的 `claim.log`。

启动器本身不碰凭据，只负责设置环境变量、调用上游脚本、记录输出。

## 用法

1. 确认本机已安装并登录 Qoder 桌面端
   （脚本会读取本机登录态，**只读不改**；也可以用 `--token` 显式指定，见下）
2. 挂到计划任务，每天固定时间执行一次：

   ```bash
   pythonw.exe qoder-run.py
   ```

3. 执行结果记在同目录的 `claim.log`

**手动试跑**（直接跑上游脚本，输出到屏幕）：

```bash
python qoder_claim.py --status       # 只读，看看当前有什么活动
python qoder_claim.py --once --json  # 领一次，输出一行 JSON
```

`--json` 的四种结论：`claimed` 领到了 / `done` 本窗口已领过 / `pending` 活动还没下发 / `error` 出错。

## 关于凭据

上游脚本默认读取本机 Qoder 客户端的登录状态，**只读、不写、不改、不外传**。

Windows 的凭据解密是与当前用户绑定的，所以需要该用户存在已登录的桌面会话。

如果不想让它读本机文件，可以显式提供 token：

```bash
set QODER_CLAIM_TOKEN=<你的 token>
```

## 来源与许可

`qoder_claim.py` 版权归 [sunp-1](https://github.com/sunp-1) 所有，MIT 许可，
原始项目：<https://github.com/sunp-1/qoder-checkin>

本项目仅补充了 `qoder-run.py` 这一层启动器。完整许可见项目根目录的 [LICENSE](../LICENSE)。
