export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        slatebg: '#07111f',
        panel: '#0f1b2d',
        line: '#1f3350',
        accent: '#6ee7f9',
        critical: '#ef4444',
        warning: '#f59e0b',
        info: '#38bdf8',
      },
      boxShadow: {
        glow: '0 10px 40px rgba(110, 231, 249, 0.12)',
      },
    },
  },
  plugins: [],
}
