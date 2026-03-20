package com.yychainsaw.service.impl;

import com.yychainsaw.mapper.UserMapper;
import com.yychainsaw.pojo.dto.UserLoginDTO;
import com.yychainsaw.pojo.dto.UserRegisteDTO;
import com.yychainsaw.pojo.entity.User;
import com.yychainsaw.pojo.vo.UserVO;
import com.yychainsaw.service.UserService;
import com.yychainsaw.utils.JwtUtil;
import com.yychainsaw.utils.Md5Util;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@Service
public class UserServiceImpl implements UserService {
    @Autowired
    private UserMapper userMapper;

    @Autowired
    private StringRedisTemplate stringRedisTemplate;

    @Override
    public User findByEmail(String email) {
        return userMapper.findByEmail(email);
    }

    @Override
    public void register(UserRegisteDTO registerDTO) {
        // 检查邮箱是否被占用
        User user = userMapper.findByEmail(registerDTO.getEmail());
        if (user != null) {
            throw new RuntimeException("该邮箱已被注册");
        }

        // 检查用户名是否被占用
        User userByName = userMapper.findByName(registerDTO.getName());
        if (userByName != null) {
            throw new RuntimeException("该用户名已被注册");
        }

        String passwordHash = Md5Util.getMD5String(registerDTO.getPassword());

        userMapper.add(registerDTO.getEmail(), registerDTO.getName(), passwordHash);
    }

    @Override
    public UserVO login(UserLoginDTO loginDTO) {
        String account = loginDTO.getAccount();
        String password = loginDTO.getPassword();

        // 1. 查找用户 (支持邮箱或用户名登录)
        User loginUser;
        if (account.contains("@")) {
            loginUser = userMapper.findByEmail(account);
        } else {
            loginUser = userMapper.findByName(account);
        }

        if (loginUser == null) {
            throw new RuntimeException("用户不存在");
        }

        // 2. 校验密码
        if (!Md5Util.getMD5String(password).equals(loginUser.getPasswordHash())) {
            throw new RuntimeException("密码错误");
        }

        userMapper.updateLastLoginTime(loginUser.getId());

        // 3. 生成 Token
        Map<String, Object> claims = new HashMap<>();
        claims.put("id", loginUser.getId());
        claims.put("username", loginUser.getName());
        String token = JwtUtil.genToken(claims);

        // 4. 把 Token 存入 Redis (有效期1小时)
        ValueOperations<String, String> operations = stringRedisTemplate.opsForValue();
        operations.set(token, token, 1, TimeUnit.HOURS);

        // 5. 封装 VO 返回
        UserVO userVO = new UserVO();
        // 自动拷贝属性 (id, email, name 等)
        BeanUtils.copyProperties(loginUser, userVO);
        // 手动设置 Token
        userVO.setToken(token);

        return userVO;

    }

    @Override
    public User findByName(String account) {
        return userMapper.findByName(account);
    }
}
