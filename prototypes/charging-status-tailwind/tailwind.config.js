/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        shell: "#F9FAFB",
        energy: "#22C55E",
        ink: "#0F172A",
        mist: "#E2E8F0",
        glow: "#DCFCE7",
      },
      fontFamily: {
        sans: [
          '"SF Pro Display"',
          '"SF Pro Text"',
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"PingFang SC"',
          '"Noto Sans SC"',
          "sans-serif",
        ],
      },
      borderRadius: {
        "4xl": "2rem",
        "5xl": "2.5rem",
      },
      boxShadow: {
        glass: "0 24px 80px rgba(15, 23, 42, 0.10)",
        card: "0 18px 48px rgba(15, 23, 42, 0.08)",
        soft: "0 10px 28px rgba(15, 23, 42, 0.05)",
      },
      backdropBlur: {
        xs: "2px",
      },
      keyframes: {
        "breathe-glow": {
          "0%, 100%": {
            opacity: "0.58",
            transform: "scale(0.9)",
            boxShadow: "0 0 0 rgba(34, 197, 94, 0)",
          },
          "50%": {
            opacity: "1",
            transform: "scale(1)",
            boxShadow: "0 0 18px rgba(34, 197, 94, 0.42)",
          },
        },
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-6px)" },
        },
      },
      animation: {
        "breathe-glow": "breathe-glow 2.6s ease-in-out infinite",
        float: "float 6s ease-in-out infinite",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
