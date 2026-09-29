import type { Config } from "tailwindcss";

// Maps each shadcn CSS variable to a Tailwind color, preserving support for
// opacity modifiers (e.g. `bg-primary/80`, `border-border`) via color-mix
// against the monochrome oklch tokens in globals.css.
// Tailwind substitutes <alpha-value> with the modifier (default 1).
const alphaVar = (name: string) =>
  `color-mix(in oklch, var(${name}) calc(<alpha-value> * 100%), transparent)`;

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        border: alphaVar("--border"),
        input: alphaVar("--input"),
        ring: alphaVar("--ring"),
        background: alphaVar("--background"),
        foreground: alphaVar("--foreground"),
        primary: {
          DEFAULT: alphaVar("--primary"),
          foreground: alphaVar("--primary-foreground"),
        },
        secondary: {
          DEFAULT: alphaVar("--secondary"),
          foreground: alphaVar("--secondary-foreground"),
        },
        destructive: {
          DEFAULT: alphaVar("--destructive"),
          foreground: alphaVar("--primary-foreground"),
        },
        muted: {
          DEFAULT: alphaVar("--muted"),
          foreground: alphaVar("--muted-foreground"),
        },
        accent: {
          DEFAULT: alphaVar("--accent"),
          foreground: alphaVar("--accent-foreground"),
        },
        popover: {
          DEFAULT: alphaVar("--popover"),
          foreground: alphaVar("--popover-foreground"),
        },
        card: {
          DEFAULT: alphaVar("--card"),
          foreground: alphaVar("--card-foreground"),
        },
      },
      fontFamily: {
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
