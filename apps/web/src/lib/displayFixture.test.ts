import { expect, it } from 'vitest';
import { displayFixtureName, displayOrderNumber, displayOrderDescription, displayFaultCode } from './displayFixture';

it('cleans only known fixture metadata without changing arbitrary user text', () => {
  expect(displayFixtureName('[T18 СИНТЕТИКА] Участок судей panel')).toBe('Участок panel');
  expect(displayFixtureName('[ДЕМО] Исполнитель 03')).toBe('Исполнитель 03');
  expect(displayOrderNumber('T18-panel-01')).toBe('01');
  expect(displayOrderNumber('T09-7-2026-10-08-0034')).toBe('0034');
  expect(displayOrderDescription('[T18 СИНТЕТИКА] Очистить кожух.')).toBe('Очистить кожух.');
  expect(displayFixtureName('ДЕМО насос T18')).toBe('ДЕМО насос T18');
  expect(displayFixtureName('[ДЕМО] Заявка пользователя')).toBe('[ДЕМО] Заявка пользователя');
  expect(displayOrderDescription('Проверить T18 и MOCK')).toBe('Проверить T18 и MOCK');
  expect(displayFaultCode('T18-jury-2026-F01')).toBe('F01');
  expect(displayFaultCode('T09-7-2026-10-08-F01')).toBe('F01');
  expect(displayFaultCode('T18-authored-custom')).toBe('T18-authored-custom');
});
