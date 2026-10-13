# 用户提供的 UI 字体

| 文件 | 字体包 | 用途 |
| --- | --- | --- |
| Skribble.ttf | Skribble.zip 中的 Skribble/Skribble-1.ttf | 左上角 ComiTrans 字标 |
| AaJinRiHuaQing-ChunLanMaoKun.ttf | AaJinRiHuaQing-ChunLanMaoKun.zip 中的 AaJinRiHuaQing-ChunLanMaoKun-2.ttf | 流式日志正文 |

两个字体由用户在 2026-09-15 提供并指定用于界面，字体二进制保持原样，内嵌版权信息未修改。压缩包内的外部网站快捷方式不作为应用资源。

通过 Qt 应用字体接口注册，使用实际字体族名。路径基于项目资源目录，沿用 `assets/ui` 的发布资源清单。日志时间戳与级别保留等宽字体，普通界面与漫画输出的嵌字配置独立。

已移除的章节横幅曾使用项目已有的 `comic-translate-ai/font_file/JP` 资源作为日文角标：

- 「漫画翻訳」：`GenJyuuGothicL-Heavy.ttf`（源柔ゴシックL Heavy），18 px。
- 「一頁ずつ磨く」：`GenEiAntiqueNv5-M.ttf`（源暎アンチック v5），16 px。

两款字体的实际族名和上述日文字形已核实。所有章节大横幅移除后，不再注册角标字体；原始字体资源仍保留，不改变漫画输出字体配置。
