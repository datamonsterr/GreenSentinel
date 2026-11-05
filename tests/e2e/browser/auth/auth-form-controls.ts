/** Scope credential controls to active Clerk inputs; ignore internal inactive fields. */
const ACTIVE_IDENTIFIER = 'input[name="identifier"]:not([tabindex="-1"])';
const ACTIVE_PASSWORD = 'input[name="password"]:not([tabindex="-1"])';

export const CREDENTIAL_FORM_SELECTOR = `form:has(${ACTIVE_IDENTIFIER})`;
export const IDENTIFIER_INPUT_SELECTOR = ACTIVE_IDENTIFIER;

export const PASSWORD_INPUT_SELECTOR = ACTIVE_PASSWORD;
export const PASSWORD_FORM_SELECTOR = `form:has(${ACTIVE_PASSWORD})`;
