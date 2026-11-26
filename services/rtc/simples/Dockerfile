# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\services\rtc\simples\Dockerfile
# Último recode: 2026-11-26 05:22:02 (America/Bahia)
# Motivo: Empacotar a versão oficial da Receita Federal para execução privada no Railway.

FROM eclipse-temurin:25-jdk AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git init regular && git -C regular fetch --depth=1 https://github.com/ReceitaFederal/calculadora-rtc-regime-regular.git def97056b799da8dd1306f4c9e47c669f4d44b4e && git -C regular checkout --detach FETCH_HEAD
WORKDIR /build/regular
RUN mkdir -p calculadora/db && sh mvnw --batch-mode flyway:migrate -Dflyway.configFiles=flyway/flyway-pro.conf
RUN git init /build/simples && git -C /build/simples fetch --depth=1 https://github.com/ReceitaFederal/calculadora-rtc-simples-nacional.git a926d5a76095ac0295a6612a9a54db7ffead2396 && git -C /build/simples checkout --detach FETCH_HEAD
WORKDIR /build/simples
RUN sh mvnw --batch-mode -DskipTests package

FROM eclipse-temurin:25-jre
WORKDIR /app
COPY --from=builder /build/regular/calculadora/db/calculadora-pro.db ./calculadora/db/
COPY --from=builder /build/simples/target/api-simples-nacional.jar ./app.jar
ENV SPRING_PROFILES_ACTIVE=offline SERVER_PORT=8080 MANAGEMENT_SERVER_PORT=8080
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70", "-jar", "/app/app.jar"]
