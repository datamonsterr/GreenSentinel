// @vitest-environment node
import { expect, test } from 'vitest';
import { primaryRoleFor, resolveInitialRoute } from '../lib/role-routing';

test.each([
  [['admin'], '/organization'],
  [['analyst', 'admin'], '/organization'],
  [['driver'], '/driver'],
  [['analyst'], '/workspace'],
  [['fraud_analyst'], '/workspace'],
  [['driver', 'analyst'], '/workspace'],
  [[], '/workspace'],
])('resolveInitialRoute(%j) -> %s', (roles, expected) => {
  expect(resolveInitialRoute(roles as string[])).toBe(expected);
});

test.each([
  [['admin'], 'admin'],
  [['driver'], 'driver'],
  [['driver', 'analyst'], 'analyst'],
])('primaryRoleFor(%j) -> %s', (roles, expected) => {
  expect(primaryRoleFor(roles as string[])).toBe(expected);
});
