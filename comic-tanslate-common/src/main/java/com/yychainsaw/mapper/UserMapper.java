package com.yychainsaw.mapper;

import com.yychainsaw.pojo.entity.User;
import jakarta.validation.constraints.NotNull;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface UserMapper {
    @Select("SELECT * FROM users WHERE email = #{email}")
    User findByEmail(String email);

    @Insert("INSERT INTO users (email, name, password_hash, created_at, updated_at) VALUES (#{email}, #{name}, #{passwordHash}, NOW(), NOW())")
    void add(String email, String name, String passwordHash);

    @Select("SELECT * FROM users WHERE name = #{account}")
    User findByName(String account);

    @Update("UPDATE users SET last_login_at = NOW() WHERE id = #{id}::uuid")
    void updateLastLoginTime(String id);
}
