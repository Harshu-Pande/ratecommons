/** CareCompass palette and type (recovered from the original build) */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: { 50: '#eef6ff', 100: '#d9eaff', 200: '#b6d5fb', 300: '#84b6f2', 400: '#4f8fe3', 500: '#2a6fd0',
                 600: '#1c56b0', 700: '#17448c', 800: '#143a73', 900: '#0f2b55' },
        mint: { 50: '#ecfdf5', 100: '#d1fae5', 200: '#a7f3d0', 300: '#6ee7b7', 400: '#34d399', 500: '#10b981',
                600: '#059669', 700: '#047857', 800: '#065f46', 900: '#064e3b' },
        sun: { 100: '#fef3c7', 300: '#fcd34d', 400: '#fbbf24', 500: '#f59e0b' },
        ink: { DEFAULT: '#0f1f33', soft: '#3d4f66', mute: '#6b7c93' },
        canvas: '#f6f8fb',
        line: '#e3e9f1',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['Plus Jakarta Sans', 'Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px #0f1f330f, 0 4px 16px #0f1f330f',
        pop: '0 12px 40px #0f1f332e',
      },
    },
  },
  plugins: [],
}
