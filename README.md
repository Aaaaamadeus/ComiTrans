<div align="center">
  <h1>Comic Translate Web 💬🎨</h1>
  <p>一个轻量、高效的自动化漫画汉化/翻译管线。集成了气泡检测、OCR 识别、大模型翻译、智能图像修补以及动态自适应嵌字排版技术。</p>
</div>

---

## ✨ 核心特性

- 🎯 **高精度气泡检测 (YOLOv5)**: 自动定位漫画中的对话气泡并提取文本区域。
- 📖 **原生漫画 OCR**: 集成专为漫画训练的 `Manga-OCR`，无惧纵横交错的日文排版和复杂背景。
- 🧠 **大模型语境翻译**: 支持配置通用的 OpenAI 兼容接口，不仅能调用最强模型，还能根据上下文实现神形兼备的翻译。
- 🧹 **无损背景修补 (LaMa)**: 精细调优的文字掩膜融合与 15px 环境拓扑感知，智能擦除原文的同时自动脑补绘制底层原画背景，彻底根除白块与文字边缘鬼影。
- ✍️ **动态自适应排版引擎**: 
  - **智能气泡测量**：能够自动解析气泡的真实不规则形状边界（Mask），而非仅仅被原本日文字符的宽度所限制。
  - **绝对几何居中**：剥离粗糙死板的左上角偏移算法，采用气泡物理核心计算重力中心，让中文优雅悬浮。
  - **防空防爆走**：字号动态适应真实留白面积，字少不突兀，字多不拥挤，还原专业汉化组的质感。

---

## 🚀 快速开始

### 1. 环境准备

推荐使用 Python 3.10+。

```bash
git clone https://github.com/yourusername/comic-translate-web.git
cd comic-translate-web
pip install -r app/requirements.txt
```

### 2. 模型下载

目前系统依赖两个核心模型，请下载后放置在指定的路径下：

- **文字与气泡检测模型**: `app/models/text_detector/comictextdetector.pt`
- **去字修补模型 (LaMa)**: `app/models/manga-lama/manga-lama.pt`

### 3. 配置核心依赖 (`config.yaml`)

项目由 `app/main/config.yaml` 统一驱动，拒绝混乱的环境变量。你需要在这里填入你的大模型 API 密钥。

```yaml
# 填入你自己的中转/官方 API Key
api_key: "sk-xxxxxx"
api_base_url: "https://api.openai.com/v1"
translation_model: "gpt-4o"
```

### 4. 投入运行

直接将需要测试翻译的漫画图片放入 `app/page/test_page` 目录下。随后在终端启动服务：

```bash
cd app/main
python main.py
```

终端将显示监视日志。当处理完毕后，你可以在 `app/page/test_page_output` 目录找到具有精美排版和干净背景的汉化图片。脚本会自动长期驻留并监听新放入的图频，**无需反复重新启动**以避免重新加载模型。

---

## 🐳 Docker 部署 (推荐)

如果你不想在本地折腾 Python 环境、依赖版本和 CUDA，使用 Docker 可以一键获取完全隔离的运行容器。

（请务必在运行前确保已在宿主机下载了模型文件并填好了 `config.yaml`）

```bash
cd comic-translate-web
docker-compose up -d
```

服务将自动挂载你的 `models`、`page` 目录以及 `config.yaml` 配置文件进入容器并开始轮询任务。

---

## 🛠️ 项目结构

```text
comic-translate-web/
├── app/
│   ├── main/
│   │   ├── main.py                       # 异步多进程任务监听入口
│   │   ├── config.yaml                   # 唯一事实配置表
│   │   ├── comic_translator_pipeline.py  # OCR / 翻译 / 修补核心调度逻辑
│   │   └── vertical_typesetter.py        # 核心：动态自适应中文排版引擎
│   ├── models/                           # 需预先放入模型的目录
│   ├── font_file/                        # 自定义预置字体（支持手写/对话/严肃等风格隔离）
│   └── page/                             # 输入/输出图床目录
└── docker-compose.yml
```

---

## 🔮 研发路线图 (Roadmap)

- [x] 基于纯配置文件的隔离机制
- [x] 背景修补光晕与鬼影消除
- [x] 基于真实掩膜 (Mask) 面积的动态排版引擎重构
- [ ] 针对剧情上下文的记忆跨图连续翻译
- [ ] 基于 UI 前端的交互式修正面版
- [ ] 根据翻译出的情感内容（愤怒、窃语等）调用多重表现渲染效果字

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 许可协议开源。
