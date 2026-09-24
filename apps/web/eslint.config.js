import js from "@eslint/js";
import react from "eslint-plugin-react";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
        React: "readonly",
      },
    },
    plugins: { react },
    rules: {
      // Core no-unused-vars cannot see JSX usage; these mark JSX identifiers used.
      "react/jsx-uses-react": "error",
      "react/jsx-uses-vars": "error",
      "no-unused-vars": ["error", { varsIgnorePattern: "^React$", args: "none" }],
    },
  },
  {
    ignores: ["dist/**", "node_modules/**"],
  },
];
