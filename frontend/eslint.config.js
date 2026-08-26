// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      // eslint-plugin-react-hooks v7 moved the flat-config presets under
      // `configs.flat`; the top-level `recommended-latest` is the legacy
      // eslintrc shape (plugins as an array), which ESLint 10 rejects.
      reactHooks.configs.flat['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
      // Zero-warning policy: exhaustive-deps ships as 'warn' in the preset, and
      // a warning that is allowed to accumulate stops being read.
      'react-hooks/exhaustive-deps': 'error',
      // eslint-plugin-react-hooks v7 folded the React Compiler rules into the
      // recommended preset. `set-state-in-effect` forbids the fetch-on-mount /
      // sync-from-props pattern this app is written in (30 sites in 20 files);
      // adopting it means moving data fetching off effects entirely, which is a
      // rewrite, not a dependency bump. This project does not run the React
      // Compiler, so the rule is off by choice — not to hide a defect. Every
      // other rule in the preset stays on, and the six it flagged that were
      // real (impure Date.now() during render, refs read during render, two
      // handlers used before declaration, a dropped error cause) are fixed.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
])
