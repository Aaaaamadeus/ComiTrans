---
license: cc-by-nc-sa-4.0
language:
- ja
pipeline_tag: image-to-text
tags:
- ocr
- manga
- japanese
- character-detection
- onnx
datasets:
- JustANormalTinkerer/animetext-ocr
tasks:
- ocr-recognition
frameworks:
- pytorch
---

# manga-ocr-charspot-small

English | [中文](README_zh.md) · [GitHub](https://github.com/muscgab/manga-ocr-charspot) · [Hugging Face](https://huggingface.co/muscgab/manga-ocr-charspot-small) · [ModelScope](https://modelscope.cn/models/muscgab/manga-ocr-charspot-small)

OCR for Japanese manga text boxes with 11M parameters. It is the larger sibling of [manga-ocr-charspot-nano](https://huggingface.co/muscgab/manga-ocr-charspot-nano) and works the same way: the model detects every character in a cropped text box, classifies it, and puts the characters in reading order with a small learned ordering head. There is no text decoder. Besides the text, it returns a box and a score for each character.

<img src="samples/char_boxes.png" width="100%">

Model output on three Read v1.3 boxes: character boxes (red) and reading order (blue). The crops are from [JMangaBench_Read](https://github.com/muscgab/JMangaBench_Read) (CC BY-NC-SA 4.0); they were picked from boxes the model reads correctly.

## Accuracy

### JMangaBench_Read v1.3 (same domain, not used for training or model selection)

[JMangaBench_Read v1.3.2](https://github.com/muscgab/JMangaBench_Read), 7,789 boxes, official scorer (RIN v1.2). "New" = the 4,660 boxes added in v1.3; Read v1.2 was the development set (see [Evaluation notes](#evaluation-notes)). All rows were scored with the same scorer from the leaderboard's prediction files.

| Model | Params | Composite ↑ | CER % ↓ | EM % ↑ | EM new % ↑ | EM printed % ↑ | EM non-printed % ↑ |
|---|---|---|---|---|---|---|---|
| **manga-ocr-charspot-small** | **11M** | 97.17 | **1.37** | **92.37** | **92.62** | **96.49** | 79.71 |
| manga-ocr-charspot-nano | 1.7M | 95.75 | 2.14 | 89.40 | 89.57 | 95.59 | 70.35 |
| manga-ocr-base-CPT-flex | 111M | **97.47** | 1.50 | 91.71 | 91.93 | 94.50 | **83.11** |
| manga-ocr-nar-small | 54M | 97.29 | 1.71 | 91.36 | 91.65 | 94.74 | 80.96 |
| manga-ocr-nar-small-distil | 30M | 96.40 | 2.29 | 89.09 | 88.95 | 93.21 | 76.41 |
| Hayai v2.5 Nova p384 | 157M | 96.64 | 2.37 | 88.20 | 88.45 | 91.95 | 76.67 |
| PaddleOCR-VL-For-Manga | 959M | 95.04 | 1.99 | 87.91 | 87.94 | 95.17 | 65.59 |
| mangaOCR | 111M | 90.27 | 4.81 | 78.51 | 78.48 | 88.34 | 48.27 |

EM is the share of boxes whose normalized prediction equals the normalized label exactly (95% CI for this model: 91.76–92.94); CER is the total edit distance divided by the total number of label characters. Composite is Read's ranking metric (1 − normalized edit distance, printed and non-printed weighted equally); the weaker non-printed side puts this model below manga-ocr-base-CPT-flex and manga-ocr-nar-small on it while its EM is higher.

### Manga109-s (different domain, not used for training)

All 123,014 text annotations of Manga109-s (scanned commercial manga, 87 volumes), cropped with the dataset's own boxes; labels and predictions normalized with RIN v1.2; EM and CER as above. Models trained on Manga109-s (Hayai, mangaOCR) are not listed. baberuOCR v1.1 (training data not published) uses the generation settings of the Read leaderboard; Preview is [manga-ocr-nar-preview](https://huggingface.co/muscgab/manga-ocr-nar-preview).

| Model | Params | EM % ↑ | CER % ↓ | EM 1–4 chars | 5–16 | 17–32 | > 32 |
|---|---|---|---|---|---|---|---|
| **manga-ocr-charspot-small** | **11M** | 91.13 | 1.44 | 93.93 | 92.03 | 88.18 | **75.11** |
| manga-ocr-charspot-nano | 1.7M | 89.10 | 1.98 | 94.27 | 90.37 | 84.46 | 60.21 |
| manga-ocr-nar-small | 54M | **92.08** | **1.39** | **95.92** | **92.23** | **90.11** | 74.39 |
| baberuOCR v1.1 | 113M | 86.68 | 2.51 | 94.73 | 87.92 | 79.75 | 54.40 |
| Preview | 196M | 86.52 | 2.46 | 91.74 | 87.30 | 83.22 | 55.59 |

Boxes per length bucket: 26,336 / 65,916 / 27,580 / 3,182.

## Speed

End to end per crop (image already decoded; preprocessing, network, decoding and reading order included), batch 1.

**CPU** (Xeon Gold 6148; 1,000 Read v1.3 boxes drawn at random with seed 0; p50 per crop; EM on the same 1,000 boxes):

| Model | Runtime | 8 threads ↓ | 4 threads ↓ | EM % ↑ |
|---|---|---|---|---|
| **manga-ocr-charspot-small** | ONNX Runtime fp32 | 19.5 ms | 27.0 ms | **93.0** |
| manga-ocr-charspot-nano | ONNX Runtime fp32 | **7.0 ms** | **7.9 ms** | 91.0 |
| manga-ocr-nar-small-distil | ONNX Runtime int8 | 37.4 ms | 54.4 ms | 89.7 |
| manga-ocr-nar-small | ONNX Runtime fp32 | 74.8 ms | 106.4 ms | 92.7 |
| Hayai v2.5 Nova p384 | PyTorch fp32 | 293.8 ms | 438.3 ms | 89.3 |
| baberuOCR v1.1 | PyTorch fp32 | 197.2 ms | 278.1 ms | 81.5 |
| PaddleOCR-VL-For-Manga | PyTorch fp32 | 1,871 ms | — | 88.9 |

Each model runs through its released package or the Read leaderboard's adapter (same generation settings) in its default CPU precision; 20 warm-up crops, then one timed pass over the 1,000 boxes, pinned to cores of one CPU socket with at most one other model running on the other socket (PaddleOCR-VL: 8 threads only). Outputs at 4 and 8 threads are identical. On 1,000 boxes the 95% CI of EM is about ±1.5–2.5 points (this model: 91.3–94.4). On an M1 Pro (8 threads, all 7,789 boxes, laptop under load) this model takes 28.1 ms per crop (p50).

**NVIDIA GPU** (RTX 2080 Ti; every row measured with the [Read leaderboard](https://github.com/muscgab/JMangaBench_Read)'s method: per image = batch 1, mean over 7,789 boxes; per page = 896 batches sized like real pages, 8.7 boxes on average, p50; max img/s = best batch size, preprocessing in 4 CPU worker processes):

| Model | Per image ↓ | Per page ↓ | Max img/s ↑ |
|---|---|---|---|
| **manga-ocr-charspot-small** (fp32, CUDA graphs) | 7.2 ms | 43.2 ms | 274 |
| manga-ocr-charspot-nano (fp16, CUDA graphs) | 5.2 ms | 28.3 ms | 633 |
| manga-ocr-nar-small-distil | 8.4 ms | 35.0 ms | 287 |
| manga-ocr-nar-small | 9.1 ms | 35.5 ms | 299 |
| Hayai v2.5 Nova p384 | 54.0 ms | 252.0 ms | 175 |
| mangaOCR | 84.9 ms | 242.4 ms | 42 |

This model runs in fp32. The resize runs on the GPU (a bit-exact port of Pillow's bicubic); box decoding and NMS run on the CPU for calls of up to 8 crops and batched on the GPU for larger calls; classification and reading order run on the GPU. CUDA graphs cover calls of up to 8 crops; larger calls run as plain PyTorch with the same results. In one process with calls of 1,024 crops it reaches 289 img/s. Measured after `warmup()` (about 7 s once at start; it captures 52 CUDA graphs, 4.4 GB of GPU memory afterwards). The CUDA backend returns the same text as the CPU ONNX package on all 7,789 Read boxes.

After an idle pause of 0.5–10 s the GPU clocks down (1,350 MHz) and the next crop takes 11.0–11.9 ms (median) instead of 6.6 ms; after 20 s idle the first crop takes 32.9 ms (Read's first-crop test). Locking the clocks avoids it.

On GPUs with less than 4 GB the backend switches to smaller calls without CUDA graphs: in a test capped at 1.4 GB of PyTorch memory it used 1.5 GB of GPU memory in total, at 17 ms per image and 240 img/s.

## Usage

```bash
git clone https://huggingface.co/muscgab/manga-ocr-charspot-small   # or: modelscope download --model muscgab/manga-ocr-charspot-small --local_dir manga-ocr-charspot-small
cd manga-ocr-charspot-small
pip install -e ".[cpu]"   # ONNX Runtime (CPU); ".[cuda]" for the PyTorch GPU backend
manga-ocr-charspot-small crop.png            # one "path<TAB>text" line per crop
manga-ocr-charspot-small --chars crop.png    # one JSON line per crop with per-character boxes and scores
```

```python
from manga_ocr_charspot_small import MangaOcrCharspotSmall

ocr = MangaOcrCharspotSmall()                   # backend "auto" (CUDA if available, else ONNX on CPU), "onnx" or "cuda"
ocr("crop.png")                         # -> str
ocr(["a.png", "b.png"])                 # -> list of strings
ocr.read("crop.png")                    # -> {"text": ..., "chars": [{"char": "今", "box": [x0, y0, x1, y1], "score": 0.93}, ...]}
ocr.warmup()                            # CUDA backend: initialise and capture the CUDA graphs once (about 7 s); no-op on CPU
```

`model.onnx` is the whole model after preprocessing in one graph (box decoding, NMS and reading order included), so it can also be used from other languages and runtimes: input `img` [1, 3, H, W] (the preprocessed crop, raw 0–255), outputs `boxes` [N, 4], `scores` [N], `ids` [N] and `order` [N] (reading order as indices); a crop without characters gives N = 0.

`read` returns the characters in reading order; boxes are in pixels of the given crop, the score is the character-centre heatmap peak. A combined `!?` glyph is one entry with a two- or three-character string. Inputs may be file paths, PIL images or uint8 RGB arrays. The model files are read from the repository directory; `MangaOcrCharspotSmall(model_dir=...)` or `MANGA_OCR_CHARSPOT_SMALL_DIR` points elsewhere. The CUDA backend (`manga_ocr_charspot_small.backends.cuda.CudaBackend`) also takes `precision="fp16"` (faster dense network; a few texts change), `graphs`, `max_batch`, `tail_budget` and `nms_budget`; by default they are chosen from the GPU memory.

## How it works

The pipeline is the one of [manga-ocr-charspot-nano](https://huggingface.co/muscgab/manga-ocr-charspot-nano#how-it-works) (figure there); this model is wider and deeper:

| | nano | small |
|---|---|---|
| Input | ≤ 196 cells of 16 × 16 px | ≤ 256 cells of 16 × 16 px |
| CNN (depthwise-separable, blocks 2 / 3 / 5) | 48 / 96 / 192 channels | 108 / 216 / 432 channels, batch norm (folded into the convolutions in the release) |
| Attention at stride 16 | 1 block, 3 heads | 2 blocks, 6 heads, QK-Norm |
| Stride-8 maps | heatmap, box, furigana flag, 64-d embedding | the same, 144-d embedding |
| Ordering / classification head | 2 attention layers, d = 64; class via a 64-d bottleneck | 4 attention layers, d = 192, 12 heads, QK-Norm; class via one linear layer on [embedding; context] |
| Parameters | 1.7M | 11.0M (10,982,979 in training; 10,960,137 after folding batch norm) |

- **Input**: the crop is resized with its aspect ratio kept and padded with the median border colour.
- **Decoding** (unchanged from nano): heatmap peaks above 0.3 → boxes → NMS (IoU 0.2, plus removal of boxes whose centre lies inside a kept box) → furigana removed → each character classified (6,817 characters + 12 combined `!?` glyphs for tate-chū-yoko).
- **Reading order**: a pairwise "next character" score and start / end scores over the detected characters; the order is read off greedily. The same mechanism covers columns, rows, multi-column boxes and curved text.

## Training

Trained from random initialisation, 40,623 steps at batch 1,024 (7 epochs + a 1,000-step cool-down), 4 × RTX 2080 Ti, fp16 mixed precision.

| Epochs | Data |
|---|---|
| 1–3 | Synthetic 4,291,646 crops with character boxes (printed 1,992,408, handwriting 2,299,238) + synthetic long text 114,804 crops (65–112 characters) + AnimeText-OCR 1,006,116 real crops (sequence confidence 0.90–0.98), text labels only; pseudo character boxes of manga-ocr-charspot-nano on 997,401 of them |
| 4–6 | the same; pseudo character boxes re-made by this model at the start of each epoch |
| 7 + cool-down | + 256,427 AnimeText-OCR crops of lower confidence (0.85–0.90); after re-labelling, 1,249,290 real crops with 15,162,804 pseudo character boxes |

- Schedule: AdamW (β2 0.95), 1,000 warm-up steps, constant learning rate 2e-3, then 1,000 steps of 1 − √t decay to 0 from the epoch-7 checkpoint. 30% of the crops are shrunk so that characters are 12–40 px.
- Real crops have no character boxes. Following [PageNet](https://arxiv.org/abs/2207.14807) (Peng et al., IJCV 2022), from epoch 4 the current model reads every real crop at the start of the epoch, its output is aligned to the text label, and only characters that match the label exactly become training boxes, merged with PageNet's score-weighted update. A re-labelling is used only if at least 80.2% of the original 1,006,116 crops are read exactly (nano's final level); the share was 86.8 / 85.5 / 84.2 / 88.2% at epochs 4–7.

## Limitations

- **Non-printed text**: EM 79.71 on Read v1.3 vs 83.11 for manga-ocr-base-CPT-flex and 80.96 for manga-ocr-nar-small. Each character is classified from its own features plus the ordering context, without a language model; look-alike characters in rough handwriting are the main error.
- **Horizontal text**: EM 75.40 on the 439 horizontal Read boxes vs 84.51 for manga-ocr-nar-small. A left–right kanji is sometimes detected as two characters (休 read as イオ, 知 as 矢の): 15 of 439 horizontal boxes vs 20 of 7,158 vertical ones.
- **Short boxes on Manga109-s**: 93.93 on 1–4 characters vs 95.92 for manga-ocr-nar-small and 94.27 for nano.
- Real-data supervision only covers characters the model already reads correctly on that crop; characters it never reads correctly are learned from synthetic data only.
- Read boxes come from one detector (AnimeText YOLO12x, tight text blocks), the same kind of crop as the real training data; Manga109-s uses its own annotation boxes.

## Evaluation notes

- Read v1.2 (the 3,129 v1.2 boxes kept in v1.3) was the development set: checkpoint choice and error analysis. The released checkpoint is the epoch-7 cool-down; the cool-downs after epochs 6, 7, 9, 10 and 12 scored 91.63–91.98 on it, within noise of each other. The decoding thresholds are nano's.
- Read v1.3 was looked at before release: its scores for the cool-downs after epochs 3, 6 and 7 were computed during training (not used for any decision), and the horizontal-text error analysis above was done on Read v1.3 boxes after the checkpoint was fixed. The 4,660 new boxes were not used for training or tuning.
- Manga109-s was not used for training, model selection or tuning.
- The Read scores are the outputs of the released ONNX package (CPU, fp32); the CUDA backend (fp32) gives the same text on all 7,789 boxes. The Manga109-s scores come from the CUDA backend.

## Acknowledgements

- [PageNet](https://arxiv.org/abs/2207.14807) (Peng et al., IJCV 2022): character detection on a grid, and weak supervision of real crops that have only text labels (pseudo character boxes matched to the label, score-weighted update across epochs).
- [CenterNet](https://arxiv.org/abs/1904.07850) (Zhou et al., 2019): character-centre heatmap with Gaussian targets and the penalty-reduced focal loss, box regression at the peak.
- [KuroNet](https://arxiv.org/abs/1910.09433) (Clanuwat et al., ICDAR 2019): reading Japanese text by per-location character detection and classification.
- Reading order as pairwise successor relations: [Zhang et al.](https://arxiv.org/abs/2409.19672) (EMNLP 2024), [Hakim et al.](https://arxiv.org/abs/2607.01018) (2026); character ordering from coordinates: [Lamb et al.](https://arxiv.org/abs/2106.06786) (2021).
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR): layout of the backbone stem, blocks and downsampling (small PP-OCR recognition backbone). [CPVT](https://arxiv.org/abs/2102.10882): positional convolution before attention. [MobileNetV3](https://arxiv.org/abs/1905.02244): hard-swish and hard-sigmoid squeeze-excite. [QK-Norm](https://arxiv.org/abs/2010.04245) (Henry et al., 2020): layer-normalized queries and keys.
- [Cluster-NMS](https://arxiv.org/abs/2005.03572): parallel NMS in pseudo-labelling, in `model.onnx` and in the CUDA backend.
- [Hägele et al.](https://arxiv.org/abs/2405.18392) (NeurIPS 2024): constant learning rate with a 1 − √t cool-down.
- [AnimeText](https://arxiv.org/abs/2510.07951) and [AnimeText-OCR](https://huggingface.co/datasets/JustANormalTinkerer/animetext-ocr): real training crops; the real kana glyphs of the synthetic handwriting were also cut from AnimeText images and upscaled with [Real-ESRGAN](https://arxiv.org/abs/2107.10833).
- [Manga109](http://www.manga109.org/) ([Matsui et al., 2017](https://arxiv.org/abs/1510.04389); [Aizawa et al., 2020](https://arxiv.org/abs/2005.04425)): Manga109-s for evaluation.
- mangaOCR, Hayai, baberuOCR and PaddleOCR-VL-For-Manga: comparison models from the Read leaderboard.

## License

Code: Apache-2.0. Weights: CC BY-NC-SA 4.0 (trained on AnimeText-OCR). Data sources and attribution: [NOTICE.md](NOTICE.md).
