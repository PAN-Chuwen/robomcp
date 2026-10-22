import type { NextConfig } from "next";

// Every page reads the session cookie and live API data, so pages render per request; Cache Components
// (prerendered static shells) would buy nothing here and is left off.
const nextConfig: NextConfig = {
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
