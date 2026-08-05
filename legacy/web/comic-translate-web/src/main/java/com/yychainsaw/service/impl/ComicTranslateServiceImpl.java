package com.yychainsaw.service.impl;

import com.yychainsaw.service.ComicTranslateService;
import org.springframework.stereotype.Service;

import java.io.File;


@Service
public class ComicTranslateServiceImpl implements ComicTranslateService {

    private static final long POLL_INTERVAL_MS = 1000;
    private static final long MAX_WAIT_MS = 120000;

    @Override
    public String translateImage(String inputPath, String outputPath) {
        // Python 文件轮询模式：文件放入 input 目录后，Python 自动检测并处理
        // 输出文件名规则：{baseName}_translated{ext}
        File inputFile = new File(inputPath);
        String baseName = inputFile.getName();
        int dotIdx = baseName.lastIndexOf('.');
        String nameWithoutExt = dotIdx > 0 ? baseName.substring(0, dotIdx) : baseName;
        String ext = dotIdx > 0 ? baseName.substring(dotIdx) : ".jpg";

        File outputDir = new File(outputPath).getParentFile();
        File expectedOutput = new File(outputDir, nameWithoutExt + "_translated" + ext);

        System.out.println("[翻译] 等待 Python 处理: " + inputFile.getName());
        System.out.println("[翻译] 期望输出: " + expectedOutput.getAbsolutePath());

        long startTime = System.currentTimeMillis();
        while (System.currentTimeMillis() - startTime < MAX_WAIT_MS) {
            if (expectedOutput.exists() && expectedOutput.length() > 0) {
                System.out.println("[翻译] 处理完成: " + expectedOutput.getName());
                return expectedOutput.getAbsolutePath();
            }
            try {
                Thread.sleep(POLL_INTERVAL_MS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new RuntimeException("等待翻译结果被中断", e);
            }
        }

        throw new RuntimeException("翻译超时（" + MAX_WAIT_MS / 1000 + "秒），请确认 Python 服务已启动");
    }
}

