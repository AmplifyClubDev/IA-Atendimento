FROM mcr.microsoft.com/playwright:v1.61.0-noble@sha256:57b65fdc9ceabe0ef613124c7bbe2babcf9362c4d85e382fe3b03604e84b428a
ENV DEBIAN_FRONTEND=noninteractive DISPLAY=:99 NODE_ENV=production TIKTOK_HEADLESS=false TIKTOK_PLAYWRIGHT_PROFILE_DIR=/data/partner-profile TIKTOK_INVITE_SERVER_HOST=127.0.0.1 TIKTOK_WARM_SERVER_PORT=8788 PORT=8080
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify tini && rm -rf /var/lib/apt/lists/*
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts
COPY . .
RUN node --test security.test.mjs interactive-policy.test.mjs session-handoff.test.mjs relation-details.test.mjs auto-recuperacao.test.mjs diagnostico.test.mjs && node --check railway-supervisor.mjs && node --check railway-login.mjs && node --check server-quente.mjs
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini","-g","--"]
CMD ["node","railway-supervisor.mjs"]
