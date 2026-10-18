# 繁体漫画嵌字字体收集

收集日期：2026-10-15。共 **10 个字体系列、12 个 TTF/OTF 文件**，字体原文件合计 **183.4 MiB**。

这批字体已全部内置在应用资源 `comic-translate-ai/font_file/TC`，翻译页和精修页可直接检索选择，首次使用无需下载或导入。发行包会同时包含原字体、授权和来源记录；不会自动改变用户已选的默认字体。

沿用项目开源免费的方向，按漫画常见嵌字用途挑选，优先使用繁体或台湾版本。这是一份用途选型清单，**不代表漫画行业使用率排名**。表中的用途为本次搭配建议。

## 字体清单与官方来源

| 字体 / 官方来源 | 本次收集字重 | 建议用途 | 原文件体积 |
| --- | --- | --- | --- |
| [源泉圓體 TW](https://github.com/ButTaiwan/gensen-font) | R / B | 日常對白、加重語氣 | 30.5 MiB |
| [jf open 粉圓](https://github.com/justfont/open-huninn-font) | Regular | 輕鬆對白、可愛語氣 | 4.7 MiB |
| [芫荽](https://github.com/ButTaiwan/iansui) | Regular | 柔和對白、內心獨白 | 9.0 MiB |
| [霞鶩文楷 TC](https://github.com/lxgw/LxgwWenkaiTC) | Regular | 自然對白、敘述文字 | 14.6 MiB |
| [內海字體 TW](https://github.com/max32002/naikaifont) | Regular | 手寫對白、氣泡外的小字 | 25.0 MiB |
| [清松手寫體 3](https://github.com/jasonhandwriting/JasonHandwriting) | Regular | 吐槽、呆萌語氣、手寫註記 | 5.8 MiB |
| [思源黑體 TC](https://github.com/adobe-fonts/source-han-sans) | Medium / Heavy | 中粗對白、喊叫、強烈語氣 | 32.6 MiB |
| [思源宋體 TC](https://github.com/adobe-fonts/source-han-serif) | Medium | 旁白、正式敘述、嚴肅氣氛 | 23.7 MiB |
| [獅尾加糖宋體 TC](https://github.com/max32002/swei-sugar) | Black | 驚叫、恐怖氣氛、擬聲大字 | 27.7 MiB |
| [大波浪圓體 TC](https://github.com/max32002/pop-gothic) | Bold | 撒嬌、搞笑、可愛擬聲字 | 9.8 MiB |

每个字体目录附上原作者 README、许可证（如上游提供）和原字体内嵌版权/授权声明；`manifest.json` 记录来源版本、下载地址、原文件 SHA256、字重、字符测试结果。字体文件保持原样。

## 优先搭配

- **一般对白**：源泉圆体 TW Regular；需要加重语气时使用同系列 Bold。轮廓清楚，圆角比纯黑体柔和。
- **轻松、可爱的对白**：jf open 粉圆；适合生活、校园题材。
- **柔和或有手写感的对白**：芫荽；偏好传承字形时可选霞鹜文楷 TC。
- **气泡外的小字、吐槽**：内海字体、清松手写体 3；保持足够字号。
- **信件、日记、轻声注记**：霞鹜文楷 TC Regular 或芫荽，搭配适当的字号和留白。
- **喊叫、强烈语气**：思源黑体 TC Heavy；字形大时可按画面使用描边和倾斜。
- **旁白、正式叙述**：思源宋体 TC Medium。
- **拟声、搞笑、夸张表情**：狮尾加糖宋体 TC Black、大波浪圆体 TC Bold；适合短句或单字。

## 繁体字形与缺字说明

- **源泉圓體 TW**：TW 月版，現代台灣通俗字形；另有 TC 丹版傳承字形可選。 本次擴展測試無缺字。
- **jf open 粉圓**：針對台灣繁體用字設計的圓體。 擴展測試缺字：麽。
- **芫荽**：接近台灣教育部標準字形；官方說明未涵蓋完整 Big5。 擴展測試缺字：麽。
- **霞鶩文楷 TC**：採傳承字形，與台灣教育部標準字形有別。 本次擴展測試無缺字。
- **內海字體 TW**：瀨戶字體繁體補字衍生，部分補字筆形和日文字形仍有差異。 本次擴展測試無缺字。
- **清松手寫體 3**：作者將第 3 款描述為「呆萌」；保留原字型內嵌授權與版權聲明。 擴展測試缺字：麽。
- **思源黑體 TC**：繁體中文台灣版本；香港字形另有 HC 版本。 本次擴展測試無缺字。
- **思源宋體 TC**：取中等字重，避免小圖下細橫筆畫過弱。 本次擴展測試無缺字。
- **獅尾加糖宋體 TC**：思源宋體橫筆加粗衍生；原作者提醒可能缺少部分符號或罕用字。 本次擴展測試無缺字。
- **大波浪圓體 TC**：手寫 POP 風；補字外形可能不一致，適合少量表情文字。 擴展測試缺字：麽。

同为繁体，不同字体可能采用台湾现代通俗字形、台湾教育部字形或传承字形，不能仅凭 TC 缩写认定字形完全相同。以上字形差别依据各作者的官方说明。

本次基础测试句：

> 你剛才說什麼？！別鬧了，這傢伙還沒回來……「這裡」才對——喵～轟！

全部 12 个字体文件均能覆盖这句文字，并通过 FontTools 字符映射检查、Pillow/FreeType 加载和实字渲染。另测试了以下字形、语气字和符号：

> 妳裏裡著着為爲麼麽說説臺灣嗚噗欸嘖囉嗯鬱龜「」『』？！……——～

其中部分字体不包含异体字“麽”，而包含常用写法“麼”。这只是小样本检查，不能据此推断所有罕见人名、地名或粤语字都完整。竖排还应检查引号、破折号、省略号和小字位置；字体含 `vert`/`vrt2` 特性不代表当前排版器一定调用它们。

芫荽使用官方 **v1.020** 发行附件；附件内字体与本次固定仓库提交的字体字节一致，原始压缩附件来源和 SHA256 已记录。字体内部版本号仍写作 1.012，这是上游文件的原始信息。其他文件来自 manifest 中固定的官方仓库提交，并核对 Git blob 字节。全部文件在 14、24、34、52、72 px 下通过基础测试句实际绘制。

另调查了 [辰宇落雁体](https://github.com/Chenyu-otf/chenyuluoyan_thin)：本次测试的 2.0 仓库文件在本机 Pillow/FreeType 绘制时报 `too many function definitions`，旧等宽版虽然能绘制，但基础测试句缺“喵”。因此本次可直接导入包不收录它，保留官方链接供其他排版环境选用。

## 使用与授权

本次选择的字体由各上游标注使用 SIL Open Font License。通常可用于商业漫画输出和软件随附，但随附字体时应保留原版权、许可证与适用的保留名称要求。具体以随附上游原文和 [SIL OFL 官方条款](https://openfontlicense.org/open-font-license-official-text/) 为准。

清松手写体上游只有 README 和字体内嵌授权声明，没有单独的许可证文本。本包保留这些原文，并另附 SIL 官方 OFL 1.1 参考模板；参考模板中的占位符不代表清松字体版权人。详见该目录 `LICENSE-NOTE.txt`。

在 ComiTrans 中，这些字体已直接出现在翻译页和精修页的字体列表，无需安装到系统。选择框采用中文名和中文粗细，原始英文名仍可检索；精修页显示可换行的完整当前名称。选择字体与简繁转换是两件事：繁体字体本身不会把简体译文转换为繁体。

## 商业字体参考

[华康新综艺体](https://www.dynacw.com.tw/product/product_download_detail.aspx?fid=110) 可作为 POP、夸张标题字的商业参考，官方页面列出 W5/W7/W9 字重及购买/授权入口。本次开源字体包不包含该字体。

## 本地文件

- 应用内置字体与授权：`comic-translate-ai/font_file/TC/`，包含 10 个编号目录。
- 正式来源及校验清单：`comic-translate-ai/font_file/TC/manifest.json`。
- 真实字样对照：`tmp/traditional-manga-fonts/font-preview.png`。
- 下载与检查记录：`tmp/traditional-manga-fonts/manifest.json`。
- 压缩包：`tmp/ComiTrans-Traditional-Manga-Fonts.zip`。

正式字体资源存放于应用字体目录并随程序打包；`tmp` 中的对照图、压缩包与收集过程文件仅作本地参考。
