/** @type {import('next').NextConfig} */
const nextConfig = {
  // Docker-Deployment: selbsttragender Server-Build (node server.js)
  output: "standalone",
  // Wissens-Dateien (Stilguide/Playbook) müssen im Serverless-Bundle liegen,
  // damit /api/skript und /api/faktencheck sie zur Laufzeit per fs lesen können.
  // (Das Dockerfile kopiert scraper/wissen zusätzlich explizit.)
  outputFileTracingIncludes: {
    "/api/skript": ["./scraper/wissen/**/*"],
    "/api/faktencheck": ["./scraper/wissen/**/*"],
  },
};

export default nextConfig;
