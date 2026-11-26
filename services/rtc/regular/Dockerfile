# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\services\rtc\regular\Dockerfile
# Último recode: 2026-11-26 05:26:26 (America/Bahia)
# Motivo: Compilar o serviço oficial com Maven instalado na imagem e executá-lo na rede privada.

FROM eclipse-temurin:25-jdk AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates maven && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git init regular && git -C regular fetch --depth=1 https://github.com/ReceitaFederal/calculadora-rtc-regime-regular.git def97056b799da8dd1306f4c9e47c669f4d44b4e && git -C regular checkout --detach FETCH_HEAD
WORKDIR /build/regular
RUN mkdir -p calculadora/db && mvn --batch-mode flyway:migrate -Dflyway.configFiles=flyway/flyway-pro.conf
RUN mvn --batch-mode -DskipTests package

FROM eclipse-temurin:25-jre
WORKDIR /app
COPY --from=builder /build/regular/calculadora/db/calculadora-pro.db ./calculadora/db/
COPY --from=builder /build/regular/target/api-regime-geral.jar ./app.jar
ENV SPRING_PROFILES_ACTIVE=offline SERVER_PORT=8080 MANAGEMENT_SERVER_PORT=8080
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70", "-jar", "/app/app.jar"]
