import { defineConfig } from 'oxlint'

export default defineConfig({
  plugins: ['typescript'],
  ignorePatterns: ['**/node_modules/**', '**/.nuxt/**', '**/.output/**', '**/.data/**', '**/dist/**', '**/assets/**'],
  rules: {
    'no-unused-vars': ['warn', { varsIgnorePattern: '^_', argsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' }],
    'no-else-return': 'error',
    'default-param-last': 'error',
    'prefer-exponentiation-operator': 'error',
    'typescript/array-type': ['error', { default: 'generic' }],
    'typescript/consistent-type-assertions': ['error', { assertionStyle: 'as', objectLiteralTypeAssertions: 'allow-as-parameter' }],
    'typescript/consistent-type-imports': ['error', { disallowTypeAnnotations: false }],
    'typescript/no-explicit-any': 'error',
    'typescript/no-inferrable-types': 'error',
    'typescript/prefer-function-type': 'error',
  },
})
