import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Repo name doubles as the GitHub Pages base path.
const repo = (process.env.VITE_REPO ?? "stevehaigh/vinted-scanner").split("/")[1];

export default defineConfig({
  plugins: [react()],
  base: `/${repo}/`,
  // The Vinted parameter table lives in the Python package: one platform of
  // truth for both parsers, so they cannot drift.
  server: { fs: { allow: [".."] } },
});
