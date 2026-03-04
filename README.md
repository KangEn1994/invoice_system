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

访问: [http://localhost:1033](http://localhost:1033)

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
- 也可以直接使用 `stack/start.sh`，它已内置 `docker-compose.yml + docker-compose.gpu.yml`，默认执行 `up -d --build`。
- 若出现 `Can not import paddle core while this file exists`，请重建 `backend` 镜像一次（修复了 paddle CPU/GPU 包冲突）：
  `./start.sh build --no-cache backend && ./start.sh up -d backend`
- 若出现 `ImportError: libGL.so.1: cannot open shared object file`，说明 OCR 依赖的 OpenCV 动态库缺失：
  `git pull` 后执行 `./start.sh build --no-cache backend && ./start.sh up -d backend`
- 若出现 `ImportError: numpy.core.multiarray failed to import`，说明 `numpy/opencv` 二进制 ABI 不匹配：
  `git pull` 后执行 `./start.sh build --no-cache backend && ./start.sh up -d backend`
- 若出现 `Cannot load cudnn shared library`：
  1. 临时恢复（不重建）：把 `stack/docker-compose.gpu.yml` 中 `OCR_USE_GPU` 改为 `"false"`，重启 backend；
  2. 根治：`git pull` 后执行 `./start.sh build --no-cache backend && ./start.sh up -d backend`（已切到 CUDA 11.8 + cuDNN8 基线）。
- 若诊断命令显示 `libcublas.so.11` 或 `libcudart.so.11.0` 缺失：
  1. 这是 CUDA 运行时库未就绪（不是业务代码问题）；
  2. 已在 GPU 镜像里切到 `nvidia/cuda:11.8.0-cudnn8-devel` 并补充 `LD_LIBRARY_PATH`；
  3. 执行 `./start.sh build --no-cache backend && ./start.sh up -d backend`。
- 若构建阶段报 `libcuda.so.1: cannot open shared object file`：
  1. 这是构建上下文中没有宿主 NVIDIA 驱动库注入导致；
  2. `libcuda.so.1` 应在容器运行时由 `nvidia-container-runtime` 注入；
  3. 构建阶段可忽略该项，运行后用 `nvidia-smi` 和 OCR 实测确认。

## 数据挂载目录
- PostgreSQL 数据: `stack/data/postgres`
- 发票文件: `stack/data/files`
- 分享 ZIP 缓存: `stack/data/zip_cache`

## start.sh 常用命令
- 启动: `./start.sh`（等价于 `up -d --build`）
- 查看日志: `./start.sh logs -f backend`
- 重建后端: `./start.sh build --no-cache backend`

## CI/CD（GitHub Actions）
仓库已内置两条工作流：
- CI: `.github/workflows/ci.yml`
  - 后端依赖安装 + Python 编译检查 + FastAPI 导入烟雾测试
  - 前端 JS 语法解析检查
  - Compose 配置解析与 Docker 镜像构建检查
- CD: `.github/workflows/cd.yml`
  - 当 `main` 分支 push 且 CI 成功后，自动 SSH 到服务器部署
  - 也支持在 Actions 页面手动触发 `workflow_dispatch`

需要在 GitHub 仓库配置以下 Secrets：
- `DEPLOY_HOST`: 服务器地址
- `DEPLOY_USER`: SSH 用户
- `DEPLOY_SSH_KEY`: 私钥内容（建议专用 deploy key）
- `DEPLOY_PORT`: SSH 端口（可选，不填默认 22）

可选仓库变量（Variables）：
- `DEPLOY_PATH`: 服务器项目路径（默认 `/home/jingjian/apps/invoice_system`）

CD 执行的核心命令：
```bash
cd <DEPLOY_PATH>
git pull
cd stack
docker compose down
sh ./start.sh up -d
```

## OCR依赖说明
- 默认本机构建不强制安装 OCR 依赖，避免 macOS 本地构建被 GPU/平台差异卡住。
- 后端若无 OCR 依赖，上传仍可成功，OCR 状态会是 `failed`，后续在服务器上可重识别。

## 常见故障排查
- 后端报 `connection to server at "db" ... server closed the connection unexpectedly`：
  1. 先看数据库日志：`cd stack && ./start.sh logs -f db`
  2. 若数据库容器反复崩溃，先单独拉起数据库：`./start.sh up -d db`
  3. 后端已内置数据库连接重试（默认最多 60 次，每次间隔 2 秒），数据库恢复后会自动连上。
- 若 `db` 日志显示数据目录损坏/版本不兼容（且你可接受清空数据）：
  1. `./start.sh down`
  2. 清空 `stack/data/postgres/*`
  3. `./start.sh up -d`
- OCR 识别失败但日志看不到明确原因：
  1. 先查 OCR 健康接口：`curl -sS http://127.0.0.1:8000/api/invoices/ocr/health -H \"Authorization: Bearer <token>\"`
  2. 前端发票列表里 `OCR=failed` 行可点击 `原因` 按钮查看后端返回的错误文本。
