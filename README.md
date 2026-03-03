# Comic Translate Web

漫画翻译工具，支持自动检测气泡、OCR 识别、翻译和嵌字。旨在为个人用户提供轻量化的漫画汉化解决方案。

## 🚀 快速开始

### 1. 环境准备

确保已安装 Python 3.10+。

```bash
git clone https://github.com/yourusername/comic-translate-web.git
cd comic-translate-web/app
pip install -r requirements.txt
```

### 2. 模型下载

下载以下模型文件并放置到对应目录：

- **文字检测模型**: `app/models/text_detector/comictextdetector.pt`
- **图像修补模型**: `app/models/manga-lama/manga-lama.pt`

### 3. 配置 API

修改 `app/main/config.yaml` 文件：

```yaml
# 翻译 API (支持 OpenAI 兼容接口)
api_key: your_api_key
api_base_url: your_api_base_url
```

### 4. 运行程序

```bash
cd main
python main.py
```

程序启动后会自动监控 `app/page/test_page` 目录，将翻译后的图片输出到 `app/page/test_page_output`。

### 🐳 Docker 部署 (推荐)

运行前请确保已下载模型文件并配置好 `config.yaml`。

由于 `docker-compose.yml` 已配置好所有挂载，直接启动即可：

```bash
docker-compose up -d
```

这将自动：
- 拉取最新镜像
- 挂载 `models`、`page` 目录和 `config.yaml` 配置文件
- 启动服务

## ✨ 功能特性

- **气泡检测**: 使用 Comic Text Detector (YOLOv5-based) 自动检测漫画中的对话气泡。
- **OCR 识别**: 集成 Manga-OCR，精准识别竖排/横排日文。
- **智能翻译**: 支持 Gemini、OpenAI 等大语言模型，结合画面上下文进行翻译。
- **背景修补**: 使用 Manga-Lama 模型自动擦除原文，生成干净底图。
- **自动嵌字**: 根据气泡类型（对话/独白/喊叫）自动选择合适的字体和排版。

## ⚙️ 配置说明

主要配置位于 `app/main/config.yaml`，修改后重启生效。

```yaml
# 目录路径
page_input_dir: page/test_page
page_output_dir: page/test_page_output

# 字体配置
font_size: 16
font_dialogue: font_file/CN/SourceHanSerifCN-Regular-1.otf
# ... 其他字体路径

# 运行选项
use_gpu: false        # 是否使用 GPU 加速
max_workers: null     # 并发进程数 (null 为自动检测)
```

## 🛠️ 项目结构

```
comic-translate-web/
├── app/
│   ├── main/
│   │   ├── main.py              # 程序入口
│   │   ├── config.yaml          # 配置文件
│   │   ├── comic_translator_pipeline.py  # 核心处理管线
│   │   └── ...
│   ├── models/                  # 模型文件存放目录
│   ├── font_file/               # 字体文件
│   └── page/                    # 输入/输出目录
└── ...
```

## 🔮 未来计划

- **字体自动适配**: 根据翻译内容情感自动选择字体。
- **Agent 模式**: 引入 Agent 架构，处理复杂排版和剧情连贯性。
- **AI 背景修补**: 引入更强的生成式模型进行背景修复。

## 📄 许可证

MIT License
