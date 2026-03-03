package com.yychainsaw.controller;

import com.yychainsaw.service.ComicTranslateService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.util.UUID;

@RestController
@RequestMapping("/comic")
public class ComicTranslateController {

    @Autowired
    private ComicTranslateService comicTranslateService;

    @PostMapping("/translateImage")
    public ResponseEntity<?> translateImage(@RequestParam("file") MultipartFile file) {
        try {
            // 1. 生成临时文件路径 (绝对路径)
            String fileName = UUID.randomUUID().toString() + ".jpg";
            File tempDirFile = new File("C:\\Users\\YYchainsaw\\IdeaProjects\\comic-translate-web-main\\comic-translate-ai\\page\\test_page");
            File outputDirFile = new File("C:\\Users\\YYchainsaw\\IdeaProjects\\comic-translate-web-main\\comic-translate-ai\\page\\test_page_output");

            File inputFile = new File(tempDirFile, fileName);
            File outputFile = new File(outputDirFile, fileName);

            // 创建目录
            if (!inputFile.getParentFile().exists()) inputFile.getParentFile().mkdirs();
            if (!outputFile.getParentFile().exists()) outputFile.getParentFile().mkdirs();

            // 2. 保存前端上传的文件
            file.transferTo(inputFile);


            String resultPath = comicTranslateService.translateImage(
                    inputFile.getAbsolutePath(),
                    outputFile.getAbsolutePath()
            );

            // 返回图片文件
            File resultFile = new File(resultPath);
            if (!resultFile.exists()) {
                return ResponseEntity.status(500).body("翻译生成文件未找到");
            }
            return ResponseEntity.ok()
                    .contentType(MediaType.IMAGE_JPEG)
                    .body(new FileSystemResource(resultFile));
        } catch (IOException e) {
            return ResponseEntity.status(500).body("文件保存失败: " + e.getMessage());
        }
    }
}
