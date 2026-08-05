# ======= 构建阶段 =======
FROM node:20-alpine as build-stage

WORKDIR /app

# 复制依赖配置
COPY package*.json ./

# 由于国内网络原因，建议使用淘宝镜像提高安装速度和成功率
RUN npm config set registry https://registry.npmmirror.com/ && npm install

# 复制源码并构建
COPY . .
RUN npm run build

# ======= 运行阶段 =======
FROM nginx:stable-alpine as production-stage

# 将构建产物复制到 Nginx 的默认静态资源目录
COPY --from=build-stage /app/dist /usr/share/nginx/html

# 注意：具体路由和反向代理规则将通过外部挂载的 default.conf 在 docker-compose 中覆盖，
# 因此此处可以直接使用基础镜像。

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
