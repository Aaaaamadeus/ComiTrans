package com.yychainsaw.exception;

import com.yychainsaw.pojo.dto.Result;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(Exception.class)
    public Result handleException(Exception e) {
        e.printStackTrace();

        return Result.error(StringUtils.hasLength(e.getMessage())? e.getMessage() : "服务器异常，请联系管理员");
    }
}
