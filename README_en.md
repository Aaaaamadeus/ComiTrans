# ComiTrans

<div align="center">

**[English](README_en.md)** ｜ **[简体中文](README.md)**

<br>

<img src="https://img.shields.io/github/v/release/Aaaaamadeus/ComiTrans?color=76bad9" alt="release">
<img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="python">
<img src="https://img.shields.io/badge/UI-PySide6-green.svg" alt="PySide6">
<img src="https://img.shields.io/badge/Inference-ONNX%20Runtime-orange.svg" alt="ONNX Runtime">
<img src="https://img.shields.io/github/stars/Aaaaamadeus/ComiTrans?color=76bad9" alt="stars">

</div>

ComiTrans is a fully local manga translation desktop client. Text detection, Japanese OCR, LLM translation, background inpainting, and Chinese typesetting all run locally on your machine, with no browser, server, or web backend required.

Since v2.1.0, detection, OCR, and inpainting are powered entirely by **ONNX Runtime**, removing PyTorch / torchvision / transformers dependencies. The app and models are released as separate packages: the app archive is about 0.4GB, and model updates no longer require re-downloading the program.

## Before / After

> [!NOTE]
> Put comparison images into `docs/images/`: `before.jpg` (original page) and `after.jpg` (translated page). They will show up here once added to the repository.

| Before | After |
| --- | --- |
| ![Before](docs/images/before.jpg) | ![After](docs/images/after.jpg) |

## Table of Contents

1. [Key Features](#key-features)
2. [Quick Start](#quick-start)
3. [Usage](#usage)
4. [Translation Pipeline](#translation-pipeline)
5. [Models](#models)
6. [Packaging & Release](#packaging--release)
7. [Project Structure](#project-structure)
8. [Changelog](#changelog)
9. [FAQ](#faq)
10. [Feedback](#feedback)
11. [License](#license)

## Key Features

- **Fully local desktop client**: PySide6 desktop app with no web pages or backend services.
- **All-ONNX inference**: text detection, Manga-OCR, and LaMa inpainting are all ONNX models; no PyTorch required.
- **Split release packages**: the app archive is about 0.4GB; models ship separately, so app updates do not require re-downloading models.
- **Startup warmup**: the AI pipeline loads automatically when the app opens.
- **GPU inference**: NVIDIA CUDA supported when the machine already has an NVIDIA driver.
- **Multimodal translation toggle**: sends the full page image to the AI and lets it configure font, size, and direction after translation; pure-text mode uses automatic typesetting.
- **Special font classification**: narration, onomatopoeia, next-episode previews, and titles are automatically matched with different open-source fonts.
- **Mask-based erasing and typesetting**: erasing only removes the detector text mask; layout area and center follow the mask.
- **Manual typesetting editor**: adjust font style, size, direction, and position per text block, then save over the output.
- **Error logs with AI diagnosis**: logs go to `Log/app.log`, diagnosis prompts are auto-generated, and multi-turn AI diagnosis is supported.
- **Batch folder selection**: pick a whole folder and images are added recursively.
- **Instant stop**: clicking stop immediately enters a cancelled state.
- **Issue feedback**: jump to your configured GitHub Issues link from the top-right button.
- **Adjustable layout**: resize the main areas, preview, and log panels by dragging.

## Quick Start

### Release users (recommended)

1. Download `ComiTrans-v2.1.0-app.zip` (program) and `ComiTrans-v2.1.0-models.zip` (models).
2. Extract the app archive into a `ComiTrans` folder.
3. Extract the models archive into the same `ComiTrans` folder; models will be merged into `ComiTrans\comic-translate-ai\models\`.
4. Double-click `ComiTrans.exe` and enter your translation API key and model on the "API Config" page.

Release users do not need to install Python, PyTorch, pip, or the CUDA Toolkit. GPU acceleration only requires an existing NVIDIA driver.

### Run from source (developers)

Python 3.12+ is recommended; an NVIDIA GPU with CUDA support is optional.

```powershell
cd D:\ComiTrans
python -m venv .venv
.\.venv\Scripts\python -m pip install -r comic-translate-ai/requirements.txt
```

Copy the example config:

```powershell
Copy-Item comic-translate-ai/main/config.example.yaml comic-translate-ai/main/config.yaml
```

Run the client:

```powershell
.\.venv\Scripts\python run.py
```

You can also double-click `start.bat`. The AI pipeline warms up automatically after launch.
## Usage

1. Click "Add Images" or "Add Folder", or drag images/folders into the window.
2. Enter API Key, Base URL, translation model, and Issue link on the "API Config" page.
3. Enable "Multimodal Translation" to send the full page image to the AI and let it configure fonts; disable it to use pure-text translation and automatic typesetting.
4. Expand "Preferences" on the translation page to fill in background prompts and Chinese character names (one per line; the AI maps them automatically).
5. Click "Start Translation" and watch the live step/status logs.
6. On failure, open the "Error Logs" page for diagnosis prompts, or click the Issue button.
7. Use the "Typesetting Editor" page to fine-tune font style, size, direction, and position per block, then save.

### Font styles

| Style | Usage | Default font |
| --- | --- | --- |
| `radiating` | Normal text / onomatopoeia | Smiley Sans Oblique |
| `narration` | Ultra-wide narration boxes | LXGW WenKai |
| `next_preview` | Next-episode preview | Klee One |
| `dialogue` | Fallback dialogue font | Source Han Sans Medium |
| `serious` | Fallback narration font | Source Han Sans Medium |
| `handwriting` | Fallback handwriting font | setofont |
| `title` | Fallback title font | Source Han Sans Heavy |

Except for next-episode previews, all text defaults to `radiating`. Ultra-wide horizontal boxes (width > height × 2.5) are automatically classified as `narration`. Every block can be overridden manually in the editor.

### Error logs & AI diagnosis

- All runtime logs are written to `Log/app.log`.
- The "Error Logs" page gathers environment info, model paths, recent logs, and stack traces.
- Copy diagnosis prompts, copy raw logs, or open the log file directly.
- AI diagnosis keeps the current log context and multi-turn memory; only "Clear Context" resets it.

## Translation Pipeline

1. **Bubble & text detection**: an ONNX detector outputs bubbles, text masks, and text lines.
2. **Japanese OCR**: ONNX Manga-OCR recognizes Japanese text. Blocks detected as English, or whose OCR output looks like garbled Latin, are kept whole: no OCR, no erasing, and no typesetting.
3. **LLM translation**: pure-text mode translates OCR results; multimodal mode sends the page image and asks the AI to configure font, size, and direction.
4. **Background inpainting**: erases only the detector text mask; simple white bubbles are filled directly, complex backgrounds use LaMa ONNX.
5. **Chinese typesetting**: font size is estimated from the mask area, text is centered on the mask centroid, orientation adapts automatically, and long text gets tighter sizing.
6. **Save & edit**: output images are saved, cleaned canvases go to `<output_dir>_cleaned/`, layout JSON goes to `<output_dir>_layout/`, and the editor lets you refine everything manually.

## Models

| Purpose | Model | Source |
| --- | --- | --- |
| Bubble & text detection | `comic-text-detector.onnx` | [mayocream/comic-text-detector-onnx](https://huggingface.co/mayocream/comic-text-detector-onnx), exported from [dmMaze/comic-text-detector](https://github.com/dmMaze/comic-text-detector) |
| Japanese OCR | `manga-ocr-onnx/` | [l0wgear/manga-ocr-2025-onnx](https://huggingface.co/l0wgear/manga-ocr-2025-onnx), based on [kha-white/manga-ocr](https://github.com/kha-white/manga-ocr) |
| LaMa inpainting | `lama-manga-dynamic.onnx` | manga-lama |

More model sources, alternative ONNX versions, and better detection candidates: [docs/ONNX_MODELS.md](docs/ONNX_MODELS.md).

## Packaging & Release

### Build the app

```powershell
.\build_app.ps1
```

By default the app is built without models. For local testing with models:

```powershell
.\build_app.ps1 -IncludeModels
```

### Generate release packages

```powershell
python package_release.py
```

This creates two archives:

- `ComiTrans-v2.1.0-app.zip`: program only, no models
- `ComiTrans-v2.1.0-models.zip`: ONNX models

Extract the models archive into `ComiTrans\comic-translate-ai\models\`.

## Project Structure

```text
ComiTrans
├── run.py                         # desktop client entry
├── comic-translate-ai/            # AI core
│   ├── main/
│   │   ├── comic_translator_pipeline.py
│   │   ├── onnx_text_detector.py  # ONNX text detection
│   │   ├── onnx_manga_ocr.py      # ONNX Japanese OCR
│   │   ├── manga_lama.py          # ONNX inpainting
│   │   └── vertical_typesetter.py # Chinese typesetting
│   ├── models/                    # model weights (beside exe in releases)
│   └── font_file/                 # Chinese fonts
├── comic_translate_desktop/       # PySide6 desktop client
├── docs/ONNX_MODELS.md            # model sources & alternatives
├── legacy/web/                    # archived web architecture
├── build_app.ps1                  # build script
└── package_release.py             # release split script
```

## Changelog

### v2.1.0 (2026-08-06)

**Architecture**

- Rebuilt as a fully local PySide6 desktop client, removing the web stack (Spring Boot / FastAPI / PostgreSQL / Redis / Nginx).
- Switched detection, OCR, and inpainting to ONNX Runtime, removing PyTorch / torchvision / transformers.
- Split releases: ~0.4GB app archive plus a separate models archive.

**New features**

- Startup warmup for the AI pipeline.
- Multimodal translation toggle with AI font/size/direction configuration.
- Manual typesetting editor with save-over.
- Error logs with AI diagnosis and multi-turn context.
- Batch folder selection, instant stop, Issue feedback, draggable layout.
- Special open-source fonts for narration, onomatopoeia, next-episode previews, and titles.

**Fixes & tuning**

- Fixed frozen exe warmup stalls (unittest exclusion, detector dynamic import, pyclipper / unidic / manga_ocr assets).
- Balanced orientation thresholds to reduce horizontal/vertical misclassification.
- Balanced font sizes: larger for vertical text, tighter for horizontal and long text; mask-area sizing and mask-centroid layout.
- Erasing now uses the detector text mask only, not the whole bubble.
- English text blocks are fully skipped: no OCR, no erasing, no typesetting; high Latin/full-width Latin ratio in OCR output is auto-detected and the original text is kept.
- Cleaned canvases moved to `<output_dir>_cleaned/`.
- Removed training/visualization dependencies (matplotlib, wandb, pandas, torchsummary).

### v1.x (archived)

- Web-based manga translation platform: Spring Boot backend, Vue frontend, PostgreSQL / Redis / Nginx, Python worker for image processing.
- Batch translation, text erasing, font classification, horizontal typesetting, hosted models.
- Archived under `legacy/web/`; old docs in `docs/README-v1.md`.

## FAQ

**Do releases require Python or the CUDA Toolkit?**

No. Extract the app and models, then run. GPU acceleration only needs an existing NVIDIA driver.

**Where do models go?**

Beside the exe at `comic-translate-ai/models/`. Release users must extract `ComiTrans-v2.1.0-models.zip` into the same `ComiTrans` folder.

**Why is English text not translated?**

The current OCR model is Japanese-only and garbles English. English is detected in two layers: detector labels marked as English, and OCR output where Latin/full-width Latin characters account for at least 40%. Matched blocks skip OCR, erasing, and typesetting so the original English stays on the page. To translate English, enable multimodal translation or wait for a future English OCR.

**Why is the app archive so small?**

Since v2.1.0 everything is ONNX and PyTorch is gone. Detection, OCR, and inpainting only need onnxruntime.

## Feedback

Report issues at [GitHub Issues](https://github.com/Aaaaamadeus/ComiTrans/issues) or use the Issue button in the app. Attach the diagnosis prompt from the "Error Logs" page when possible.

## License

- Project code is released under the license in the repository.
- Fonts: Smiley Sans, LXGW WenKai, Klee One, Source Han Sans/Serif, and setofont are open-source fonts with their own licenses.
- Models: comic-text-detector, manga-ocr, and manga-lama are open-source; see [docs/ONNX_MODELS.md](docs/ONNX_MODELS.md).