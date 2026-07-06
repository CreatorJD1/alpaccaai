import { defineConfig } from "vite";

export default defineConfig({
  define: {
    __BUNDLED_DEV__: true,
  },
  server: {
    allowedHosts: true,
  },
});
