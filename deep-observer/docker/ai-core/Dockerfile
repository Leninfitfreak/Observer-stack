FROM golang:1.24-alpine AS builder
WORKDIR /src
COPY ai-core/go.mod ./ai-core/go.mod
RUN cd ai-core && go mod download
COPY ai-core ./ai-core
RUN cd ai-core && CGO_ENABLED=0 GOOS=linux go build -o /out/ai-core ./cmd/server

FROM alpine:3.21
RUN apk add --no-cache ca-certificates tzdata kubectl
WORKDIR /app
COPY --from=builder /out/ai-core /app/ai-core
COPY .env /app/.env
COPY docker/ai-core/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
EXPOSE 8081
CMD ["/app/entrypoint.sh"]
