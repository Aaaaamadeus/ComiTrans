package com.yychainsaw.service.impl;

import com.yychainsaw.service.ComicTranslateService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.Map;


@Service
public class ComicTranslateServiceImpl implements ComicTranslateService {
    @Autowired
    private RestTemplate restTemplate;

    private static final String PYTHON_API_URL = "http://localhost:8000/translate";

    @Override
    public String translateImage(String inputPath, String outputPath) {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);

            Map<String, String> requestBody = new HashMap<>();
            requestBody.put("input_path", inputPath);
            requestBody.put("output_path", outputPath);

            HttpEntity<Map<String, String>> request = new HttpEntity<>(requestBody, headers);

            Map response = restTemplate.postForObject(PYTHON_API_URL, request, Map.class);

            if (response != null && "success".equals(response.get("status"))) {
                System.out.println("Python 处理成功");
                return (String) response.get("output_path");
            } else {
                throw new RuntimeException("Python 服务返回异常: " + response);
            }

        } catch (Exception e) {
            System.err.println("调用 Python 模型失败，请检查 python api.py 是否正在运行。错误信息: " + e.getMessage());
            throw new RuntimeException("翻译服务暂不可用", e);
        }
    }
}

