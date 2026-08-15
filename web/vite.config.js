import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// IMPORTANT: `base` must match your repo name for GitHub Pages project sites,
// e.g. if your repo is github.com/you/mortgage-tracker, base should be
// "/mortgage-tracker/". If you rename the repo, update this too.
export default defineConfig({
  plugins: [react()],
  base: "/mortgage-tracker/",
});
