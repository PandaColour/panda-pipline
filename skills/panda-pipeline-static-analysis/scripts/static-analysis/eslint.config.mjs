export default [
  {
    rules: {
      "no-magic-numbers": ["warn", { ignore: [0, 1, 2, -1], ignoreArrayIndexes: true, ignoreDefaultValues: true }],
      "complexity": ["warn", { max: 15 }],
      "max-statements": ["warn", { max: 60 }],
      "max-params": ["warn", { max: 6 }],
      "max-depth": ["warn", { max: 5 }],
    },
  },
];
