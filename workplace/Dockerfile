# syntax=docker/dockerfile:1

# Gradle Wrapper로 실행 배포본을 만드는 빌드 단계입니다.
FROM eclipse-temurin:17-jdk-jammy AS builder

WORKDIR /workspace

# 의존성 정의를 먼저 복사해 소스 변경 시에도 Docker 빌드 캐시를 활용합니다.
COPY gradlew gradlew
COPY gradle gradle
COPY settings.gradle gradle.properties ./
COPY app/build.gradle app/build.gradle
RUN chmod +x gradlew && ./gradlew :app:dependencies --no-daemon

COPY app/src app/src
RUN ./gradlew :app:installDist --no-daemon

# 실행 이미지에는 JRE와 애플리케이션 실행 파일만 포함합니다.
FROM eclipse-temurin:17-jre-jammy

RUN groupadd --system workplace \
    && useradd --system --gid workplace --home-dir /opt/workplace workplace

WORKDIR /opt/workplace
COPY --from=builder --chown=workplace:workplace \
    /workspace/app/build/install/app/ ./

USER workplace
EXPOSE 8080

ENTRYPOINT ["/opt/workplace/bin/app"]
