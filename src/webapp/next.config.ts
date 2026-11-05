import fs from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const packageJson = JSON.parse(
  fs.readFileSync(path.resolve(process.cwd(), "package.json"), "utf8")
);

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_PUBLIC_GIS_OPTIMIZED_TEST === 'true' ? '.next-gis' : '.next',
  env: {
    NEXT_PUBLIC_APP_VERSION: packageJson.version,
  },
  allowedDevOrigins: [
    "datamonster",
    "datamonster:3000",
    "100.116.207.93",
    "100.116.207.93:3000",
    "localhost",
    "localhost:3000",
    "localhost:3100",
    "127.0.0.1",
    "127.0.0.1:3000",
    "127.0.0.1:3100",
  ],
  webpack(config, { isServer }) {
    const isE2E =
      process.env.NEXT_PUBLIC_E2E_TEST === "true" ||
      process.env.E2E_TEST === "true" ||
      process.env.TEST_AUTH_ENABLED === "true";

    if (isE2E) {
      config.resolve = config.resolve || {};
      config.resolve.alias = config.resolve.alias || {};
      config.resolve.alias["@clerk/nextjs$"] = path.resolve(
        process.cwd(),
        "test-support/clerk-mock.tsx"
      );
    }

    if (!isServer) {
      config.plugins.push({
        apply(compiler: any) {
          compiler.hooks.thisCompilation.tap("MapLibreSharedWorker", (compilation: any) => {
            const { RawSource } = compiler.webpack.sources;
            compilation.emitAsset(
              "static/media/maplibre-gl-shared.mjs",
              new RawSource(fs.readFileSync(path.resolve(process.cwd(), "node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs"))),
            );
          });
        },
      });
    }
    return config;
  },
  async rewrites() {
    const backend = (
      process.env.API_BASE_URL ||
      process.env.NEXT_PUBLIC_API_BASE_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      (process.env.NODE_ENV === "development"
        ? "http://127.0.0.1:8000"
        : "https://greensentinel-backend-production.up.railway.app")
    ).replace(/\/+$/, "");
    if (!/^https?:\/\//.test(backend)) return [];
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backend}/api/v1/:path*`,
      },
      {
        source: "/test/api/v1/:path*",
        destination: `${backend}/test/api/v1/:path*`,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
