# ======= 打包阶段 =======
FROM maven:3-eclipse-temurin-17 AS build
WORKDIR /app

# 复制 pom 和源代码进行构建
COPY pom.xml .
COPY src ./src

# 如果需要加速，可以在外部环境提前缓存 ~/.m2 但在容器里为了干净直接发版
RUN mvn clean package -DskipTests

# ======= 运行阶段 =======
FROM eclipse-temurin:17-jre
WORKDIR /app

COPY --from=build /app/target/*.jar app.jar

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
