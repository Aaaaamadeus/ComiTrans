<div align="center">
  <h1>Comic Translate Web 💬🎨</h1>
  <p>一个基于 Docker 微服务架构的端到端 AI 漫画自动翻译平台。<br/>集成气泡检测、OCR 识别、大模型翻译、智能图像修补及动态排版引擎，通过 Nginx 网关统一对外提供服务。</p>
</div>

---

## ✨ 核心特性

- 🎯 **高精度气泡检测 (YOLOv5)**: 自动定位漫画中的对话气泡并提取文本区域边缘。
- 📖 **原生漫画 OCR**: 集成专为漫画训练的 `Manga-OCR`，无惧纵横交错的日文排版和复杂背景。
- 🧠 **全局语境大模型翻译**: 支持配置通用的 OpenAI 兼容接口，不仅能调用前沿大模型，还能基于全图上下文实现神形兼备的翻译。
- 🧹 **无损背景修补 (LaMa)**: 精细调优的文字掩膜融合与 15px 环境拓扑感知，智能擦除原文的同时自动脑补绘制底层原画背景，彻底根除白块与文字边缘鬼影。
- ✍️ **动态自适应排版引擎**: 
  - **智能气泡测量**：自动解析气泡真实不规则包围盒与面积（Mask），而非死板受限于原本文字的包围框。
  - **绝对几何居中**：剥离粗糙死板的左上角偏移算法，根据文本掩膜的物理重力中心进行坐标计算，让中文优雅悬浮框内。
  - **防空防爆走**：字号动态适应真实留白面积，字少不突兀，字多不拥挤，还原专业汉化组的质感。

---

## ⚙️ 处理流程

整个自动化汉化管线的执行逻辑主要分为以下关键步骤（详见 `comic_translator_pipeline.py`）：

1. **图像扫描与气泡检测 (Detection)**：通过基于 YOLO 打造的专用气泡检测模型（`comic-text-detector`）扫描完整的漫画页面，圈定所有的对话气泡边界框（Bounding Box），并提取其像素面积掩膜（Mask），同时对其分类为横排、竖排及其特有的对话风格。
2. **文本区域提取与识别 (Manga-OCR)**：针对检测到的气泡裁切出有效图像区块，送入专精漫画不规则排版的 OCR 识别引擎，提取出原始上下文段落。
3. **批量多模态大模型翻译 (LLM Translation)**：将全页提取出的日文字符序列，连带原始漫画位图以 Base64 形式整体打包，通过提示词工程并行发送至兼具视觉功能的大模型（如 GPT-4o），利用画面场景及人物神态作为上下文，实现自然流畅的中区二次元信达雅翻译。
4. **智能背景修补与掩膜清理 (Inpainting)**：
   - 对于纯净的**白底气泡**，直接做膨胀擦除涂白。
   - 对于**干扰性背景**（如渐变、网点、环境溢涂），将气泡和往外延展的 15px 周边像素送入图像修补模型 **LaMa**，结合其全局感知能力将原有文字抹去，推断并重绘画图底色与网纹。
5. **动态嵌字排版融合 (Typesetting)**：在已被清理成无字干将的底图画布上，解析原始日文字符留下的真实掩膜孔洞。根据翻译成型的中文及设定的对话风格字体类型，经过折行及大小适应计算和重力居中逻辑进行嵌字，最终渲染并导出具备精美视觉排版的成品图像。

---

## 🧠 实现原理

- **基于目标检测的文字定位**：常规 OCR 模型在面对破碎或无明显段落边界的气泡时难以提取完整的语义序列。本项目使用经过万张漫画数据集特殊微调的目标检测架构，将特定的发声气泡（常规、爆炸框、内心独白等）视为独立特征物件精准拆解。
- **高鲁棒环境补全网络 (LaMa)**：修补日漫气泡最大痛点是底层的网点纸极易断层，或出现明显抹除污染。本项目所引用框架引入了 Fast Fourier Convolutions（快速傅里叶卷积），使其能在较浅的层级极度放飞感受野感知全局图像拓扑结构，修补大面积气泡的同时保持原作背景的一致性。
- **基于物理引力的重力排版算法**：传统的自动化嵌字工具常受制于“包围框”，难以在椭圆或多边形气泡里排出版面舒适的文本。本项目放弃了基于中心点的硬靠，转而依据遮罩像素的真实质量与分布解算出最适合的中心悬浮坐标（通过 `VerticalTypesetter` 处理），避免出现中文段落溢出边界的问题。

---

## 🚀 快速开始

### 1. 环境准备

推荐使用 Python 3.10+。

```bash
git clone https://github.com/yourusername/comic-translate-web.git
cd comic-translate-web
pip install -r comic-translate-ai/requirements.txt
```

### 2. 在线 API 配置

项目由 `comic-translate-ai/main/config.yaml` 统一驱动底层逻辑，但**无需手动编辑**此文件。

当你启动并访问 Web UI 后，直接点击右上角的“设置”按钮，在弹出的“翻译 API 设置”对话框中：
- 输入你的 **API Key**
- 输入你的 **API Base URL**（如 `https://api.openai.com/v1`）
- 填入你使用的**翻译模型**（如 `gpt-4o`, `gemini-2.5-flash`）

所有设置点击“保存”后即时生效，无需重启任何服务。

### 3. 网页端使用

服务相关容器/程序启动后，直接在浏览器中访问 Web 页面（本地部署默认为 `http://localhost` 或相应的 Nginx 地址）。

在网页主工作区中：
1. **上传图片**：直接拖拽或选择需要汉化的原始漫画图片。
2. **自动处理**：系统将在后台自动进行气泡检测、OCR 识别、AI 翻译、底层修补去字以及最终的自动中文嵌字排版。
3. **获取结果**：处理完成后，一张兼具精美排版与无损背景的汉化成品图将直接呈现在网页端供您预览下载。整个流程全自动联动，无需繁琐的人工干预。

---

## 🐳 系统架构与 Docker 部署

### 整体架构

项目采用 **Docker Compose 多服务微架构**，由 5 个容器协同运行：

```text
                        +---------------------------------------------+
                        |              Docker Compose                 |
  Browser --> :80 -->   |  +---------------------------+              |
                        |  |   Nginx (nginx-ui)        |              |
                        |  |   - /      -> Vue SPA     |              |
                        |  |   - /api/  -> Spring Boot |              |
                        |  |   - /process-image -> AI  |              |
                        |  |   - /config -> AI config  |              |
                        |  +------+----------+---------+              |
                        |         |          |                        |
                        |    +----v---+ +----v--------+               |
                        |    |web-api | |  ai-worker  |               |
                        |    | :8080  | |    :8000    |               |
                        |    |Spring  | |  FastAPI +  |               |
                        |    | Boot   | | AI Pipeline |               |
                        |    +---+--+-+ +-------------+               |
                        |        |  |                                 |
                        |   +----v--v--+  +---------+                 |
                        |   |   db     |  |  redis  |                 |
                        |   | PG 15   |  |  7      |                 |
                        |   +----------+  +---------+                 |
                        +---------------------------------------------+
```

| 服务 | 容器名 | 说明 |
|------|--------|------|
| **Nginx** | `comic-nginx-ui` | 统一入口网关，分发前端静态资源 + 反向代理后端 API 和 AI 服务 |
| **Spring Boot** | `comic-web-api` | Java 后端 API，对接 PostgreSQL / Redis |
| **FastAPI AI Worker** | `comic-ai-worker` | Python AI 推理引擎，承载完整翻译管线 |
| **PostgreSQL 15** | `comic-db` | 业务数据持久化存储（命名卷 `postgres-data`） |
| **Redis 7** | `comic-redis` | 高速缓存服务 |

### 快速启动

```bash
cd comic-translate-web
docker-compose up -d
```

在线 API 密钥等配置，待容器启动后直接进入 Web 端的“设置”弹窗即可操作，**无需重启容器即时生效**。

### Nginx 网关路由

Nginx 作为唯一对外暴露端口（`:80` / `:443`），实现以下路由策略：

| 路径 | 目标 | 特殊配置 |
|------|------|----------|
| `/` | Vue SPA 静态资源 | `try_files` 支持前端路由回退 |
| `/api/` | Spring Boot `:8080` | 透传 `X-Real-IP`、`X-Forwarded-For`；配置 CORS 跨域头 |
| `/process-image` | AI Worker `:8000` | 关闭 `proxy_buffering`；`read_timeout 300s`；`body_size 50M` |
| `/config` | AI Worker `:8000` | 配置管理（读取脱敏 / 写入热更新） |

生产环境已部署 SSL 证书，启用 HTTPS 并强制 TLSv1.2 / TLSv1.3。

### 镜像构建优化

AI Worker 镜像基于 `python:3.10-slim`，采用以下策略控制体积与加速构建：
- 分层构建顺序优化，最大化 Docker 层缓存命中率
- 阿里云 APT 镜像源加速系统依赖安装
- `--no-cache-dir` + APT 缓存清理减少冗余层
- 模型文件、配置、日志通过 **Volume 热挂载**至宿主机，迭代无需重建镜像

### 日志归集

各服务日志通过 Docker Volume 统一挂载至宿主机 `./Log` 目录：
- **AI Worker**：`tee` 双写，标准输出 + 文件同步记录
- **Spring Boot**：`logging.file.name` 配置输出
- **Nginx**：access / error log 分离

便于运维排查，也为后续接入 ELK / Loki 等日志分析平台预留了接口。

---

## 🛠️ 项目结构

```text
comic-translate-web/
├── docker-compose.yml                     # 多服务编排定义
├── Dockerfile                             # AI Worker 镜像构建
├── init.sql                               # PostgreSQL 初始化脚本
│
├── nginx/
│   ├── conf.d/
│   │   └── default.conf                   # Nginx 路由与反向代理配置
│   └── certs/                             # SSL 证书目录
│
├── comic-translate-ai/                    # AI 推理引擎 (FastAPI)
│   ├── main/
│   │   ├── app.py                         # FastAPI 应用入口 & 配置热更新
│   │   ├── config.yaml                    # 唯一事实配置表
│   │   ├── comic_translator_pipeline.py   # OCR / 翻译 / 修补核心调度
│   │   ├── vertical_typesetter.py         # 动态自适应中文排版引擎
│   │   └── manga_lama.py                  # LaMa 图像修补封装
│   ├── models/                            # AI 模型文件 (Volume 挂载)
│   ├── font_file/                         # 自定义预置字体
│   └── page/                              # 输入/输出图床目录
│
├── comic-translate-web/                   # Spring Boot 后端 API
├── comic-translate-ui/                    # Vue 前端 (构建后由 Nginx 分发)
└── Log/                                   # 统一日志归集目录 (Volume 挂载)
```

---

## 🔮 研发路线图 (Roadmap)

- [x] 基于纯配置文件的隔离机制
- [x] 背景修补光晕与鬼影消除
- [x] 基于真实掩膜 (Mask) 面积的动态排版引擎重构
- [x] Docker Compose 多服务容器化编排
- [x] Nginx 反向代理网关 + SSL/HTTPS
- [x] FastAPI 封装 AI Pipeline 为 RESTful API
- [x] 运行时配置热更新（无需重启容器）
- [x] 多容器日志统一归集
- [ ] 针对剧情上下文的记忆跨图连续翻译
- [ ] 基于 UI 前端的交互式修正面版
- [ ] 根据翻译出的情感内容（愤怒、窃语等）调用多重表现渲染效果字
- [ ] 接入 CI/CD 自动构建与镜像推送
- [ ] Prometheus + Grafana 服务监控

---

## 🤝 致谢与引用的开源项目

本项目的核心能力离不开以下优秀的开源组件和模型，向各位原作者和社区贡献者致以崇高的敬意：

- **[comic-text-detector](https://github.com/wszydlo/comic-text-detector)** by @wszydlo：项目依赖其核心结构提供高精度的气泡检测和漫画文字定位。(基于 **GPL-3.0 License**)
- **[yolov5](https://github.com/ultralytics/yolov5)** by @Ultralytics：核心目标检测网络框架所使用的著名 YOLOv5 检测基础。(基于 **GPL-3.0 / AGPL-3.0 License**)
- **[manga-ocr](https://github.com/kha-white/manga-ocr)** by @kha-white：为复杂日文多排版结构微调过的卓越 OCR 光学字符识别引擎。(基于 **Apache-2.0 License**)
- **[lama (Large Mask Inpainting)](https://github.com/advimman/lama)** by SAIC-MDAL：提供了对漫画中复杂背景拓扑进行智能重建修补和字形鬼影无损擦除的核心修复模型。(基于 **Apache-2.0 License**)
- **[SegmenTron](https://github.com/LikeLy-Journey/SegmenTron)**：检测器中使用的掩蔽分割和验证逻辑参考片段。(基于 **Apache-2.0 License**)

---

## 📄 开源协议

本项目的主干代码自身基于 **[MIT License](LICENSE)** 开源发布。

> **⚠️ 特别声明 / Disclaimer：**
> 由于本项目及其部分底层检测器模型（如 `comic-text-detector` 及由 `Ultralytics` 提供的 `YOLOv5` 网络）使用了基于 **GPL-3.0 (及衍生的强传染性)** 的开源协议。
> 因此，严格意义上如果您将本流水线系统用于二次开发分发或商业闭源项目用途，务必仔细知悉并遵守相关上游项目的 **GNU General Public License v3.0** 开源义务，以避免违反开源限制或承担相应的授权风险责任。
