FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN pip install --no-cache-dir \
    manga-ocr

COPY app /app

ENV PYTHONPATH=/app

CMD ["python", "-c", "print('Docker container ready')"]
