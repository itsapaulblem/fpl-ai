/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Football pitch palette — dark turf greens with gold accents
        bg: "#071c12",
        // Cards: near-black with a faint green tint so they pop against the green pitch background.
        panel: "#0a0f0c",
        panel2: "#141b16",
        border: "#243b2c",
        muted: "#7fb89a",
        text: "#eef8ef",
        accent: "#22c55e",        // bright grass green (link / CTA)
        accent2: "#ffd24a",        // trophy gold for highlights
        warn: "#f59e0b",
        danger: "#ef4444",
        gkp: "#facc15",
        def: "#60a5fa",
        mid: "#86efac",
        fwd: "#f87171",
        pitch: "#166534",
        pitchDeep: "#052e16",
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
