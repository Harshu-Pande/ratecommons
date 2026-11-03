/** RateCommons palette and type. `brand` is the commons green; `mint` is the secondary slate blue
 * (kept under its old name so the patient pages restyle without edits); `ink` is navy. */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: { 50: '#eef6f2', 100: '#d6ebe2', 200: '#add6c5', 300: '#7dbba3', 400: '#4a9c80', 500: '#23805f',
                 600: '#0f6b52', 700: '#0a5843', 800: '#0a4636', 900: '#0b3a2e' },
        mint: { 50: '#eef4f9', 100: '#d9e6f1', 200: '#b3cde3', 300: '#85aed0', 400: '#5a8eba', 500: '#3b74a3',
                600: '#2d5f88', 700: '#254d6e', 800: '#1f3f5a', 900: '#1a3349' },
        sun: { 100: '#fef3c7', 300: '#fcd34d', 400: '#fbbf24', 500: '#f59e0b' },
        clay: { 50: '#fbf1ec', 100: '#f5ddd2', 500: '#b45a35', 600: '#a4462b', 700: '#86381f' },
        ink: { DEFAULT: '#0e1b2b', soft: '#3a4a58', mute: '#5a6b7b' },
        night: { DEFAULT: '#0e1b2b', 2: '#13253a', line: '#2c3d50', text: '#c3ced6' },
        sea: '#8fd3bc',
        canvas: '#f3f7f5',
        line: '#dce3e0',
      },
      fontFamily: {
        sans: ['"Public Sans Variable"', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['"Source Serif 4 Variable"', 'Georgia', 'serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px #0e1b2b0f',
        pop: '0 12px 40px #0e1b2b2e',
      },
      maxWidth: { site: '1200px' },
    },
  },
  plugins: [],
}
