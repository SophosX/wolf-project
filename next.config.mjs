/** @type {import('next').NextConfig} */
const nextConfig = {
  // Wissens-Dateien (Stilguide/Playbook) müssen im Serverless-Bundle liegen,
  // damit /api/skript und /api/faktencheck sie zur Laufzeit per fs lesen können.
  outputFileTracingIncludes: {
    "/api/skript": ["./scraper/wissen/**/*"],
    "/api/faktencheck": ["./scraper/wissen/**/*"],
  },
};

export default nextConfig;
