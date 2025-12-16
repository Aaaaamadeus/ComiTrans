package com.yychainsaw.service;

import com.yychainsaw.pojo.dto.UserLoginDTO;
import com.yychainsaw.pojo.dto.UserRegisteDTO;
import com.yychainsaw.pojo.entity.User;
import com.yychainsaw.pojo.vo.UserVO;

public interface UserService {
    User findByEmail(String email);

    void register(UserRegisteDTO registeDTO);

    User findByName(String account);

    UserVO login(UserLoginDTO loginDTO);
}
