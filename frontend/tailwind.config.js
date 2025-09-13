/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cream: '#F5F1EB',
        'near-black': '#121212',
        tomato: '#D6423E',
        'deep-green': '#1E3A34',
      },
      fontFamily: {
        'display': ['Cormorant Garamond', 'serif'],
        'body': ['Inter', 'sans-serif'],
      },
      fontSize: {
        'display': ['clamp(3rem, 8vw, 6rem)', { lineHeight: '0.9', letterSpacing: '-0.02em' }],
      },
      maxWidth: {
        '5xl': '64rem',
      }
    },
  },
  plugins: [],
}