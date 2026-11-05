// @vitest-environment node
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { compile as compileTailwind } from 'tailwindcss';
import { describe, expect, it } from 'vitest';

const globalsPath = path.resolve(__dirname, '../../../app/globals.css');

function darkVariantBlock(): string {
  const css = readFileSync(globalsPath, 'utf8');
  const start = css.indexOf('@custom-variant dark');
  expect(start).toBeGreaterThanOrEqual(0);
  let depth = 0;
  for (let i = css.indexOf('{', start); i < css.length; i++) {
    if (css[i] === '{') depth++;
    if (css[i] === '}' && --depth === 0) return css.slice(start, i + 1);
  }
  throw new Error('unterminated @custom-variant dark');
}

const require = createRequire(import.meta.url);

async function compile(candidate: string): Promise<string> {
  const input = `@import "tailwindcss/theme.css";\n${darkVariantBlock()}\n@tailwind utilities;`;
  const compiler = await compileTailwind(input, {
    base: path.dirname(globalsPath),
    loadStylesheet: async (id: string, base: string) => {
      const resolved = require.resolve(id, { paths: [base] });
      return { path: resolved, base: path.dirname(resolved), content: readFileSync(resolved, 'utf8') };
    },
  });
  return compiler.build([candidate]);
}

describe('dark variant', () => {
  it('applies dark: utilities inside an element with the .dark class', async () => {
    const css = await compile('dark:bg-slate-950');
    expect(css).toMatch(/:where\(\.dark, \.dark \*\)/);
  });

  it('keeps OS-preference dark outside the driver scope', async () => {
    const css = await compile('dark:bg-slate-950');
    expect(css).toMatch(/prefers-color-scheme: dark/);
    expect(css).toMatch(/\[data-theme-scope\]/);
  });
});
