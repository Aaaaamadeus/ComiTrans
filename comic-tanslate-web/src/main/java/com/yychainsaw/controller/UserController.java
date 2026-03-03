package com.yychainsaw.controller;

import com.yychainsaw.pojo.dto.UserLoginDTO;
import com.yychainsaw.pojo.dto.Result;
import com.yychainsaw.pojo.dto.UserRegisteDTO;
import com.yychainsaw.pojo.vo.UserVO;
import com.yychainsaw.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/user")
@Validated
public class UserController {
    @Autowired
    private StringRedisTemplate stringRedisTemplate;
    @Autowired
    private UserService userService;

    @PostMapping("/register")
    public Result register(@RequestBody @Validated UserRegisteDTO registeDTO) {
        userService.register(registeDTO);

        return Result.success();
    }

    @PostMapping("/login")
    public Result login(@RequestBody @Validated UserLoginDTO loginDTO) {
       UserVO userVO = userService.login(loginDTO);
        return Result.success(userVO);
    }
}
