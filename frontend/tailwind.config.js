/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Core Surfaces (Slate-Steel Blue Design System)
        'sr-bg': '#172033',
        'sr-sidebar': '#1D2940',
        'sr-topbar': '#202E46',
        'sr-card': '#26364F',
        'sr-elevated': '#2D405B',
        'sr-section': '#223149',
        'sr-input': '#1C2A40',
        'sr-border': '#3B4D66',
        'sr-divider': '#33455E',

        // Semantic Accents
        'sr-primary': '#82A9FF',
        'sr-secondary': '#A4BEFF',
        'sr-teal': '#61C7B2',
        'sr-violet': '#B1A0F8',
        'sr-success': '#63D6A7',
        'sr-warning': '#F2C777',
        'sr-error': '#F18C9C',
        'sr-info': '#85B8F9',

        // Typography Colors
        'sr-text-primary': '#F0F4FC',
        'sr-text-secondary': '#C1CCDE',
        'sr-text-muted': '#95A6BE',

        // Compatibility Aliases for Smooth Transition
        'sr-indigo': '#82A9FF',
        'sr-blue': '#85B8F9',
        'sr-cyan': '#61C7B2',
        'sr-hover': '#2D405B',
        'sr-border-subtle': '#33455E',
        'sr-bg-sec': '#223149',
        'sr-text': '#F0F4FC',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        'subtle': '0 2px 6px -1px rgba(10, 16, 28, 0.35)',
        'card': '0 4px 16px -2px rgba(10, 16, 28, 0.45)',
        'elevated': '0 8px 24px -4px rgba(8, 14, 26, 0.55)',
        'dropdown': '0 12px 32px -4px rgba(8, 14, 26, 0.65)',
      },
      borderRadius: {
        'xl': '0.75rem',
        '2xl': '1rem',
      }
    },
  },
  plugins: [],
}
