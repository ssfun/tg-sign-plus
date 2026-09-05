import next from 'eslint-config-next';

const config = [
  ...next,
  { ignores: ['.next/**', 'out/**', 'node_modules/**', 'next-env.d.ts'] },
  // Static export hydrates persisted preferences in effects. Keep compiler
  // performance suggestions visible while correctness rules remain errors.
  { rules: { 'react-hooks/set-state-in-effect': 'warn' } },
];
export default config;
