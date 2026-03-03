#!/bin/bash

set -e

# 定义颜色
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}开始安装 Comic Translate Web...${NC}"

# 设置安装目录
INSTALL_DIR="comic-translate"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo -e "${GREEN}创建目录结构...${NC}"
mkdir -p app/main
mkdir -p app/page/test_page
mkdir -p app/page/test_page_output
mkdir -p app/models/text_detector
mkdir -p app/models/manga-lama
mkdir -p app/font_file

# 下载配置文件
echo -e "${GREEN}下载配置文件...${NC}"
# 注意：请将 yourusername 替换为您的 GitHub 用户名
REPO_URL="https://raw.githubusercontent.com/yourusername/comic-translate-web/main"

if [ -f "docker-compose.yml" ]; then
    echo "docker-compose.yml 已存在，跳过下载"
else
    curl -sSL "$REPO_URL/docker-compose.yml" -o docker-compose.yml
fi

if [ -f "app/main/config.yaml" ]; then
    echo "config.yaml 已存在，跳过下载"
else
    curl -sSL "$REPO_URL/app/main/config.yaml" -o app/main/config.yaml
fi

echo -e "${GREEN}安装完成！${NC}"
echo "请执行以下步骤完成配置："
echo "1. 编辑 app/main/config.yaml 填入您的 API Key 和模型配置"
echo "2. 将模型文件放入 app/models/ 对应目录"
echo "3. 运行 'docker-compose up -d' 启动服务"
