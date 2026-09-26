/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Neutral, brand-agnostic palette so this is easy to re-skin later.
        brand: {
          50: "#eef4ff",
          100: "#dbe6fe",
          500: "#3b6ef6",
          600: "#2f57d1",
          700: "#2745a8",
        },
      },
    },
  },
  plugins: [],
};
