# Wolf Radar — Next.js-App (standalone) für den VPS-Betrieb
# Build:  docker compose build radar
# Läuft intern auf :3000, nach außen nur über Caddy erreichbar.

# ---- deps ----
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- build ----
FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---- run ----
FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
# fs-Reads zur Laufzeit (Wissen/Watchlist) unabhängig vom Output-Tracing sicherstellen
COPY --from=build /app/scraper/wissen ./scraper/wissen
COPY --from=build /app/scraper/watchlist.json ./scraper/watchlist.json
# BEWUSST NICHT kopiert: scraper/lauf_lokal.sh — dadurch deaktiviert sich der
# On-Demand-Nachschub im App-Container sauber selbst; das Scraping übernimmt
# der scraper-Container per Cron.
# Seed für den Erststart + Mountpoint fürs gemeinsame daten-Volume
COPY deploy/seed/daten /seed/daten
COPY deploy/app-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/daten
EXPOSE 3000
ENTRYPOINT ["/entrypoint.sh"]
