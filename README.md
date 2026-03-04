# 个人发票管理系统（MVP）

## 技术栈
- 前端: 原生 HTML/CSS/JS
- 后端: FastAPI
- 数据库: PostgreSQL
- 部署: Docker Compose

## 目录结构
- `backend/`: FastAPI 服务
- `frontend/`: 静态页面
- `docker/`: Dockerfile 与 nginx 配置
- `stack/`: compose 文件与数据挂载目录

## 功能
- 管理员登录（access + refresh，长期登录态）
- 发票上传（jpg/png/pdf 单页）
- OCR识别与手动修正
- 标签管理（单条/批量设置）
- 列表筛选（关键词、日期、金额、标签、OCR状态、排序）
- 多选生成分享、按筛选全量生成分享
- 公开分享页下载单文件与ZIP
- 分享链接手动失效
- 分享访问日志查看

## 快速启动（本机/macOS 通用）
```bash
cd stack
docker compose up -d --build
```

访问: [http://localhost:8080](http://localhost:8080)

默认管理员:
- 用户名: `admin`
- 密码: `admin123456`

## Linux + NVIDIA GPU 启动（服务器）
```bash
cd stack
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

说明:
- `docker-compose.gpu.yml` 使用 `docker/backend-gpu.Dockerfile`。
- GPU镜像里通过 `paddlepaddle-gpu` + `paddleocr` 启用OCR。
- 如果你的 CUDA 版本不同，请调整 `stack/docker-compose.gpu.yml` 中的 `PADDLE_GPU_PACKAGE` 与 `PADDLE_WHL_URL`。
- 也可以直接使用 `stack/start.sh`，它已内置 `docker-compose.yml + docker-compose.gpu.yml + docker-compose.live-code.yml`。

## 数据挂载目录
- PostgreSQL 数据: `stack/data/postgres`
- 发票文件: `stack/data/files`
- 分享 ZIP 缓存: `stack/data/zip_cache`

## 开发模式（减少重建镜像）
首次构建后，可以把代码目录挂载进容器，后续改代码基本不需要重建。

### 本机/CPU 模式
```bash
cd stack
docker compose -f docker-compose.yml -f docker-compose.live-code.yml up -d
```

### Linux + NVIDIA 模式
```bash
cd stack
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.live-code.yml up -d
```

说明:
- `backend` 挂载 `../backend`，并以 `uvicorn --reload` 启动。
- `frontend` 挂载 `../frontend` 到 nginx 静态目录。
- 只有依赖变化（例如 `requirements*.txt` 变更）时，才需要重新 `--build`。

## OCR依赖说明
- 默认本机构建不强制安装 OCR 依赖，避免 macOS 本地构建被 GPU/平台差异卡住。
- 后端若无 OCR 依赖，上传仍可成功，OCR 状态会是 `failed`，后续在服务器上可重识别。
