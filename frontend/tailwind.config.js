/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        green: { 500: "#22c55e", 400: "#4ade80" },
        red: { 500: "#ef4444", 400: "#f87171" },
      },
    },
  },
  plugins: [],
};
