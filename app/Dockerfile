FROM python:3.10-slim
MAINTAINER Aaaaamadeus 2094941626@qq.com

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_DEFAULT_TIMEOUT=1000

COPY requirements.txt .

# 分步安装，防止爆服务器内存
RUN pip install --no-cache-dir torch==2.3.0 torchvision==0.18.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir paddlepaddle==2.6.1 -i https://pypi.tuna.tsinghua.edu.cn/simplee
# 安装剩余依赖
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

CMD ["python", "main/main.py"]