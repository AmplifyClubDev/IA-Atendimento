FROM mcr.microsoft.com/playwright:v1.61.0-noble
ENV DEBIAN_FRONTEND=noninteractive DISPLAY=:99 NODE_ENV=production TIKTOK_HEADLESS=false TIKTOK_PLAYWRIGHT_PROFILE_DIR=/data/partner-profile TIKTOK_INVITE_SERVER_HOST=127.0.0.1 TIKTOK_WARM_SERVER_PORT=8788 PORT=8080
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify tini && rm -rf /var/lib/apt/lists/*
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts
COPY . .
RUN node --test security.test.mjs trava-chrome.test.mjs && node --check railway-supervisor.mjs && node --check railway-login.mjs && node --check server-quente.mjs
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini","-g","--"]
CMD ["node","railway-supervisor.mjs"]
