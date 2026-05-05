/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Chelsea palette — based on official #034694 royal blue
        bg: "#04122e",
        panel: "#0a1d44",
        panel2: "#0e2654",
        border: "#1b3470",
        muted: "#8aa0c8",
        text: "#eef2ff",
        accent: "#3da5ff",       // bright cyan-blue (link / CTA)
        accent2: "#ffd24a",       // Chelsea gold for highlights
        warn: "#f59e0b",
        danger: "#ef4444",
        gkp: "#facc15",
        def: "#60a5fa",
        mid: "#34d399",
        fwd: "#f87171",
        chelsea: "#034694",
        chelseaDeep: "#021a3a",
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};
