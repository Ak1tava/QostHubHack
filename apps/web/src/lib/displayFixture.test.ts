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

it.each([
  ['[ДЕМО] Насос 01', 'Насос 01'],
  ['[ДЕМО] Компрессор 02', 'Компрессор 02'],
  ['[ДЕМО] Электродвигатель 03', 'Электродвигатель 03'],
  ['[ДЕМО] Вентилятор 04', 'Вентилятор 04'],
  ['[ДЕМО] Подшипник 31', 'Подшипник 31'],
  ['[ДЕМО] Масло 32', 'Масло 32'],
  ['[ДЕМО] Уплотнение 33', 'Уплотнение 33'],
  ['[ДЕМО] Крепёж 34', 'Крепёж 34'],
  ['[ДЕМО] Фильтр 35', 'Фильтр 35'],
  ['[ДЕМО] Насосная', 'Насосная'],
  ['[ДЕМО] Компрессорная', 'Компрессорная'],
  ['[ДЕМО] Электроцех', 'Электроцех'],
  ['[ДЕМО] Вентиляция', 'Вентиляция'],
  ['[ДЕМО] Насосная / 7-2026-10-08', 'Насосная'],
  ['[ДЕМО] Бригада 1 / 7-2026-10-08', 'Бригада 1'],
  ['[ДЕМО] Бригада 3', 'Бригада 3'],
  ['[T18 СИНТЕТИКА] Участок судей jury-2026', 'Участок'],
  ['[T18 СИНТЕТИКА] Бригада судей jury-2026-prepared-v2', 'Бригада'],
  ['[ДЕМО] Насос 01 пользователя', '[ДЕМО] Насос 01 пользователя'],
  ['[ДЕМО] Насос 1', '[ДЕМО] Насос 1'],
  ['[ДЕМО] Иной агрегат 01', '[ДЕМО] Иной агрегат 01'],
  ['Участок jury-2026', 'Участок jury-2026'],
])('formats only the known fixture catalog name %s', (name, expected) => {
  expect(displayFixtureName(name)).toBe(expected);
});
