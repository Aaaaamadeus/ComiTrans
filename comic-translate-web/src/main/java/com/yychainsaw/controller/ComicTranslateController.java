package com.yychainsaw.controller;

import com.yychainsaw.pojo.dto.Result;
import com.yychainsaw.service.ComicTranslateService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.*;
import java.util.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

@RestController
@RequestMapping("/comic")
public class ComicTranslateController {

    @Autowired
    private ComicTranslateService comicTranslateService;

    private static final String INPUT_DIR = "C:\\Users\\YYchainsaw\\IdeaProjects\\comic-translate-web-main\\comic-translate-ai\\page\\test_page";
    private static final String OUTPUT_DIR = "C:\\Users\\YYchainsaw\\IdeaProjects\\comic-translate-web-main\\comic-translate-ai\\page\\test_page_output";

    @PostMapping("/translateImage")
    public ResponseEntity<?> translateImage(@RequestParam("file") MultipartFile file) {
        try {
            String fileName = UUID.randomUUID().toString() + ".jpg";
            File tempDirFile = new File(INPUT_DIR);
            File outputDirFile = new File(OUTPUT_DIR);

            File inputFile = new File(tempDirFile, fileName);

            if (!tempDirFile.exists()) tempDirFile.mkdirs();
            if (!outputDirFile.exists()) outputDirFile.mkdirs();

            file.transferTo(inputFile);

            String resultPath = comicTranslateService.translateImage(
                    inputFile.getAbsolutePath(),
                    outputDirFile.getAbsolutePath()
            );

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

    @PostMapping("/translateImages")
    public ResponseEntity<?> translateImages(@RequestParam("files") MultipartFile[] files) {
        if (files == null || files.length == 0) {
            return ResponseEntity.badRequest().body(Result.error("请至少上传一张图片"));
        }
        if (files.length > 50) {
            return ResponseEntity.badRequest().body(Result.error("单次最多上传50张图片"));
        }

        File tempDirFile = new File(INPUT_DIR);
        File outputDirFile = new File(OUTPUT_DIR);
        if (!tempDirFile.exists()) tempDirFile.mkdirs();
        if (!outputDirFile.exists()) outputDirFile.mkdirs();

        List<File> resultFiles = new ArrayList<>();
        List<String> originalNames = new ArrayList<>();
        List<String> errors = new ArrayList<>();

        for (int i = 0; i < files.length; i++) {
            MultipartFile file = files[i];
            String originalName = file.getOriginalFilename() != null ? file.getOriginalFilename() : "image_" + i + ".jpg";
            try {
                String fileName = UUID.randomUUID().toString() + ".jpg";
                File inputFile = new File(tempDirFile, fileName);

                file.transferTo(inputFile);

                String resultPath = comicTranslateService.translateImage(
                        inputFile.getAbsolutePath(),
                        outputDirFile.getAbsolutePath()
                );

                File resultFile = new File(resultPath);
                if (resultFile.exists()) {
                    resultFiles.add(resultFile);
                    originalNames.add(originalName);
                } else {
                    errors.add(originalName + ": 翻译生成文件未找到");
                }
            } catch (Exception e) {
                errors.add(originalName + ": " + e.getMessage());
            }
        }

        if (resultFiles.isEmpty()) {
            return ResponseEntity.status(500).body(Result.error("所有图片翻译失败: " + String.join("; ", errors)));
        }

        // 打包成zip返回
        try {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            try (ZipOutputStream zos = new ZipOutputStream(baos)) {
                for (int i = 0; i < resultFiles.size(); i++) {
                    File resultFile = resultFiles.get(i);
                    String entryName = "translated_" + originalNames.get(i);
                    zos.putNextEntry(new ZipEntry(entryName));

                    try (FileInputStream fis = new FileInputStream(resultFile)) {
                        byte[] buffer = new byte[8192];
                        int len;
                        while ((len = fis.read(buffer)) > 0) {
                            zos.write(buffer, 0, len);
                        }
                    }
                    zos.closeEntry();
                }
            }

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
            headers.setContentDispositionFormData("attachment", "translated_comics.zip");

            return ResponseEntity.ok()
                    .headers(headers)
                    .body(baos.toByteArray());
        } catch (IOException e) {
            return ResponseEntity.status(500).body(Result.error("打包文件失败: " + e.getMessage()));
        }
    }
}
