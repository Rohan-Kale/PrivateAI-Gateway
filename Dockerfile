FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /privateai ./cmd/privateai

FROM build AS integration-test
ENV CGO_ENABLED=0
ENTRYPOINT ["go", "test", "./internal/gateway", "-run", "TestPostgresPolicyCASAndCacheVersion", "-count=1", "-v"]

FROM alpine:3.22
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 app
COPY --from=build /privateai /usr/local/bin/privateai
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["privateai"]
