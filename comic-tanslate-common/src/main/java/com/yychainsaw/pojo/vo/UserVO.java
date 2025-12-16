package com.yychainsaw.pojo.vo;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;

@Data
public class UserVO {
    private String id;
    private String email;
    private String name;
    private OffsetDateTime createdAt;
    private String token;
}
