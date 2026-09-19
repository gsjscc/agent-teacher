# 项目说明

## 浏览器工具使用规范

- 优先使用 `get_page_text` / `read_page` 直接读取页面文字内容，减少交互轮次和 token 消耗
- 非必要不要截图（`computer` 的 screenshot/zoom）；确需截图时，先告知用户原因再截
- 能一次性用 `browser_batch` 批量执行的点击/输入/导航操作，尽量合并成一次调用，不要逐步单独调用
- 同一个操作（点击/输入/连线等）尝试 3 次仍不成功，不要继续硬试、不要换着花样反复摸索，立刻停下来向用户说明卡在哪一步、报错/现象是什么，请用户帮忙确认或直接操作

## 生产服务器（外部agent托管）

- 2026-09-19 起，`测试外部agent服务/server.py` 正式托管在阿里云轻量应用服务器上，取代之前不稳定的"本机+cloudflared临时隧道"方案。
- **连接方式**：`ssh -i .env 里"private key"字段指向的 .pem 文件路径 root@.env 里"公网ip"字段` ——IP、用户名(root)、私钥路径都记在项目根目录 `.env` 里（`.env` 已在 `.gitignore`，不进版本库；私钥 `.pem` 文件本身也已用 `*.pem` 规则忽略，不要提交）。
- 服务器上代码路径：`/opt/agent-teacher`，是这个 GitHub 仓库（gsjscc/agent-teacher，公开仓库）的 `git clone`。更新代码：`ssh` 上去后 `cd /opt/agent-teacher && git pull`，服务端 `.env`（含 `QIANFAN_API_KEY`）需要单独 `scp` 同步，不随 git 走。
- 服务用 systemd 托管：`systemctl status/restart/stop agent-teacher`，开机自启+崩溃自动重启（`/etc/systemd/system/agent-teacher.service`），不要再用 nohup 手动跑。
- 服务监听 8899 端口，公网访问前必须去阿里云控制台"防火墙"里放行该端口（TCP/0.0.0.0/0）——控制台防火墙规则无法通过 SSH 命令行修改，只能引导用户去控制台操作。
