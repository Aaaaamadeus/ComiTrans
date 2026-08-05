# 旧 Web 架构存档

此目录保存 ComiTrans 重构为纯本地客户端之前的 Web 实现，包含：

- `comic-translate-ui/`：Vue + Element Plus 前端
- `comic-translate-web/`：Spring Boot 后端
- `comic-translate-ai` 的 FastAPI 入口（`fastapi_app.py`）
- `nginx/`、`Dockerfile`、`docker-compose.yml`、`init.sql`：容器编排与数据库初始化

这些文件已不再参与当前架构运行。新的本地客户端入口是根目录的 `run.py`。
