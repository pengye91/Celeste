import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  // Force development mode so React's dev build is loaded. The production
  // build (react.production.js) does NOT export `act`, which breaks
  // @testing-library/react's render/fireEvent when NODE_ENV=production leaks
  // from the shell. Tests should always run against the dev build.
  define: {
    "process.env.NODE_ENV": JSON.stringify("development"),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    env: {
      NODE_ENV: "development",
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
