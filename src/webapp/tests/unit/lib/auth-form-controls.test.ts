// @vitest-environment jsdom
import { within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import {
  CREDENTIAL_FORM_SELECTOR,
  IDENTIFIER_INPUT_SELECTOR,
  PASSWORD_INPUT_SELECTOR,
  PASSWORD_FORM_SELECTOR,
} from '../../../../../tests/e2e/browser/auth/auth-form-controls';

afterEach(() => document.body.replaceChildren());

describe('real account credential submit control', () => {
  it.each([
    ['identifier', CREDENTIAL_FORM_SELECTOR, IDENTIFIER_INPUT_SELECTOR, 'Continue'],
    ['password', PASSWORD_FORM_SELECTOR, PASSWORD_INPUT_SELECTOR, 'Sign in'],
  ])('finds the active %s form with an untyped credential control', (name, formSelector, inputSelector, label) => {
    document.body.innerHTML = `
      <form><input name="${name}" tabindex="-1" /><button>Continue</button></form>
      <button>Continue with Google</button>
      <form>
        <button type="submit" hidden></button>
        <input name="${name}" />
        <button>${label}</button>
      </form>`;
    const form = document.querySelector<HTMLElement>(formSelector)!;
    const submit = within(form).getByRole('button', { name: /^(Continue|Sign in)$/i });
    expect(submit.textContent).toBe(label);
    expect(submit.getAttribute('type')).toBeNull();
    expect(form.querySelector(inputSelector)?.getAttribute('tabindex')).toBeNull();
  });
});
