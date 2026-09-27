/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Flood severity ramp — also used for map markers so the legend, the
        // pins and the verdict card cannot drift apart.
        level: {
          normal: '#16a34a',
          puddle: '#65a30d',
          shallow: '#eab308',
          deep: '#f97316',
          severe: '#dc2626',
          closed: '#7f1d1d',
        },
      },
      fontFamily: {
        sans: ['Noto Sans Thai', 'Sarabun', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
