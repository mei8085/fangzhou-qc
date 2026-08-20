# qc-eval remote (u03l) 一次性准备

工作机 SSH 别名 `u03l`，Ubuntu 24.04。已经装好 docker.io + docker-compose-v2 + rsync。

## 已完成的事

1. `sudo apt install docker.io docker-compose-v2 rsync`
2. `sudo usermod -aG docker fz`（重登生效；免 sudo 跑 docker）
3. `/etc/docker/daemon.json` 配国内 registry mirror（`docker.m.daocloud.io` / `dockerproxy.com` / 腾讯云 / 网易云）
4. 预拉了 `postgres:15-alpine`、`redis:7-alpine`、`python:3.11-slim`
5. `~/qc-eval/{tasks,state}/` 已建好

## 本机（Windows）需要有

- `~/.ssh/config` 里 `Host u03l` 段（走 key 免密登录）
- 装了 `ssh` / `scp` / `rsync`（Windows OpenSSH + rsync via `choco install rsync` 或 WSL）
- Python 3.11 + Playwright + Pillow + openpyxl（跟 qc-eval 主流程一致）

## 目录约定

```
u03l:~/qc-eval/
├── tasks/<TASK_ID>/
│   ├── docker-compose.yml       # 由 u03l.py 渲染并 scp 上来
│   ├── init-db.sh               # postgres init：建 4 库
│   └── <CODE>/                  # rsync 自本机 tasks/<TASK_ID>/extracted/<CODE>/
└── state/                       # 预留
```

## 常用命令

```bash
# 探活
python skills/qc-eval/scripts/u03l.py check-host

# 起某题的栈（rsync 前置）
python skills/qc-eval/scripts/u03l.py sync-code TASK_ID CODE1 CODE2 ...
python skills/qc-eval/scripts/u03l.py ensure-up TASK_ID CODE1 CODE2 ...

# 看栈状态
python skills/qc-eval/scripts/u03l.py status TASK_ID
python skills/qc-eval/scripts/u03l.py list-tasks

# 销毁（带 -v 清 volume）
python skills/qc-eval/scripts/u03l.py down TASK_ID
```

## 关机注意

u03l 断电后 `check-host` 会打印明确的开机提示、退出码 2；`run.py emit` 会立即 stop。不会有任何 fallback 把 verifiable 悄悄降级到 mock。
