/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Football pitch palette — dark turf greens with gold accents
        bg: "#071c12",
        panel: "#0c2818",
        panel2: "#103020",
        border: "#1b5030",
        muted: "#6aaa84",
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
