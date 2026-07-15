import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

const TEST_AUTH_TOKEN = "test-only-continuity-token-000000000000000000000000";
process.env.LEASE_AUTH_TOKEN ??= TEST_AUTH_TOKEN;

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: {
          LEASE_AUTH_TOKEN: TEST_AUTH_TOKEN,
        },
      },
    }),
  ],
  test: {
    include: ["test/**/*.test.ts"],
  },
});
