# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\services\rtc\danfse\Dockerfile
# Último recode: 2026-11-26 05:22:02 (America/Bahia)
# Motivo: Empacotar a versão oficial da Receita Federal para execução privada no Railway.

FROM golang:1.27.1 AS builder
WORKDIR /build
RUN git init danfse && git -C danfse fetch --depth=1 https://github.com/ReceitaFederal/calculadora-rtc-gerador-danfse.git 8d79e6b2f7fad6375340afcb51c85ed370c64a14 && git -C danfse checkout --detach FETCH_HEAD
WORKDIR /build/danfse
RUN CGO_ENABLED=0 go build -trimpath -o /tmp/danfse-service ./cmd/danfse

FROM alpine:3.23
RUN apk add --no-cache ca-certificates tzdata
ENV TZ=America/Bahia SERVER_PORT=8080 OTEL_SDK_DISABLED=true
COPY --from=builder /tmp/danfse-service /usr/local/bin/danfse-service
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/danfse-service"]
