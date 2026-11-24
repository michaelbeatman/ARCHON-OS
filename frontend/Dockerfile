FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a
# F-063: Multi-Arch-Index-Digest von node:22-alpine (Node 22, alpine 3.24).
# Aufgeloest am 24.11.2026 via `docker buildx imagetools inspect node:22-alpine`.

WORKDIR /app

# Copy package files
COPY package*.json ./

# F-064: strikt lockfile-basiert. Kein `|| npm install`-Fallback, der die
# CI-Gate `npm ci` (ci.yml:62-64) unterlaufen wuerde.
RUN npm ci

# Copy application source
COPY . .

# Build Next.js application
RUN npm run build

EXPOSE 3005

ENV PORT=3005
ENV NODE_ENV=production

CMD ["npm", "run", "start"]
