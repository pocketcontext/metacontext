# Optional local image. No production deployment or backup resources are provisioned.
FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS reader
WORKDIR /ui
RUN npm install --global pnpm@10.33.2
COPY ui/package.json ui/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY ui/ ./
RUN pnpm typecheck && pnpm test && pnpm build

FROM golang:1.27.1-trixie@sha256:a4d1d139d0b0e7313de2fbe7cf4e27e3b934c164c5c58b33af44af2e9ba2fc4f AS build
ARG TARGETARCH
# Never download another Go toolchain: a go.mod that asks for a newer Go fails the build instead.
ENV GOTOOLCHAIN=local CGO_ENABLED=1

WORKDIR /src
COPY POCKETCONTEXT_VERSION /tmp/POCKETCONTEXT_VERSION
RUN set -eu; \
    revision="$(cat /tmp/POCKETCONTEXT_VERSION)"; \
    if ! grep -Eqx '[0-9a-f]{40}' /tmp/POCKETCONTEXT_VERSION; then \
      echo "POCKETCONTEXT_VERSION must hold a 40-character commit SHA" >&2; exit 1; \
    fi; \
    echo "fetching github.com/pocketcontext/pocketcontext at ${revision}"; \
    git init -q .; \
    git remote add origin https://github.com/pocketcontext/pocketcontext.git; \
    git fetch -q --depth 1 origin "${revision}"; \
    git checkout -q --detach FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = "${revision}"
RUN go mod download && go mod verify
# The flags of pocketcontext's Makefile, plus -trimpath and a stripped binary.
RUN mkdir -p /out && go build -trimpath -tags sqlite_math_functions -ldflags '-s -w' -o /out/pocketcontext ./cmd/pocketcontext \
    && /out/pocketcontext --version

FROM debian:trixie-20260918-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/* && mkdir /storage && chown 10001:10001 /storage
WORKDIR /app
COPY --from=build /out/pocketcontext /usr/local/bin/pocketcontext
COPY POCKETCONTEXT_VERSION pocketcontext.json ./
COPY pb_migrations/ ./pb_migrations/
COPY pb_hooks/ ./pb_hooks/
COPY --from=reader /ui/dist/ ./ui/dist/
USER 10001:10001
VOLUME /storage
EXPOSE 8080
ENTRYPOINT ["pocketcontext", "serve", "--http=0.0.0.0:8080", "--dir=/storage/pb_data"]
