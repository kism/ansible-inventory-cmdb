import { expect, test } from 'vitest'
import { compareCells } from './sort.ts'

test('IP addresses sort numerically, across the 32-bit sign boundary', () => {
  const ips = ['192.168.1.10', '10.0.0.2', '192.168.1.9', '10.0.0.10']
  expect(ips.sort(compareCells)).toEqual(['10.0.0.2', '10.0.0.10', '192.168.1.9', '192.168.1.10'])
})

test('anything else sorts case-insensitively', () => {
  expect(['b', 'A', '-', '1.2.3'].sort(compareCells)).toEqual(['-', '1.2.3', 'A', 'b'])
})
