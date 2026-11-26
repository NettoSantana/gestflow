# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\services\rtc\regular\Dockerfile
# Último recode: 2026-11-26 05:31:26 (America/Bahia)
# Motivo: Instalar o Maven oficial com checksum sem baixar outro runtime Java no build.

FROM eclipse-temurin:25-jdk AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 --max-time 120 \
    https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.5/apache-maven-3.9.5-bin.tar.gz -o /tmp/maven.tar.gz \
    && echo "4810523ba025104106567d8a15a8aa19db35068c8c8be19e30b219a1d7e83bcab96124bf86dc424b1cd3c5edba25d69ec0b31751c136f88975d15406cab3842b  /tmp/maven.tar.gz" | sha512sum -c - \
    && tar -xzf /tmp/maven.tar.gz -C /opt && rm /tmp/maven.tar.gz
ENV PATH=/opt/apache-maven-3.9.5/bin:${PATH}
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
