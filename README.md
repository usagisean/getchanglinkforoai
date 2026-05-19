# ChatGPT 支付长链生成器 v2

基于 FastAPI 重构，支持 Docker 一键部署到 VPS。

## 快速部署（Ubuntu VPS）

### 1. 安装 Docker

```bash
curl -fsSL https://get.docker.com | sh
```

### 2. 上传项目到 VPS

```bash
# 本地执行：将项目打包上传
scp -r ./chatgpt-payurl root@YOUR_VPS_IP:/opt/chatgpt-payurl
```

### 3. 配置环境变量

```bash
cd /opt/chatgpt-payurl
cp .env.example .env
nano .env   # 修改 ACCESS_PASSWORD
```

### 4. 启动

```bash
docker compose up -d --build
```

访问 `http://YOUR_VPS_IP:8000` 即可使用。

### 5. 查看日志

```bash
docker compose logs -f app
```

### 6. 更新代码后重新部署

```bash
docker compose down
docker compose up -d --build
```

---

## 启用 HTTPS（需要域名）

1. 将域名 A 记录指向 VPS IP
2. 编辑 `Caddyfile`，替换 `pay.yourdomain.com` 为你的域名
3. 编辑 `docker-compose.yml`，取消 `caddy` 部分的注释
4. 重新启动：`docker compose up -d --build`

Caddy 会自动申请并续期 Let's Encrypt 证书。

---

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

---

## 隐私说明

- 服务端不保存 token、代理、优惠码或生成结果
- 代理地址仅保存在用户浏览器 localStorage
- 设置 ACCESS_PASSWORD 后需密码才能访问
