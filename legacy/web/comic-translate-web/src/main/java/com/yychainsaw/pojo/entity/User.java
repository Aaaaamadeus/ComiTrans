package com.yychainsaw.pojo.entity;

import com.fasterxml.jackson.annotation.JsonFormat;
import jakarta.validation.constraints.NotEmpty;
import lombok.Data;

import java.net.URL;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;

@Data
public class User {
    @NotEmpty
    private String id;
    private String email;
    private String name;
    @NotEmpty
    private String passwordHash;
    private URL avatarUrl;
    private String role;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
    private OffsetDateTime lastLoginAt;
}
