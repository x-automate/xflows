import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        React: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["error", { varsIgnorePattern: "^React$", args: "none" }],
    },
  },
  {
    ignores: ["dist/**", "node_modules/**"],
  },
];
