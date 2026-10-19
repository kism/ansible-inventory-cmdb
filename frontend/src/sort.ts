// The hosts table's click-a-heading sort, and the sort by IP address it gets on render.

const IPV4 = /^(25[0-5]|2[0-4]\d|[01]?\d\d?)(\.(25[0-5]|2[0-4]\d|[01]?\d\d?)){3}$/

// Multiplied, not shifted: << is 32-bit signed, which put 128.0.0.0 and up before 10.0.0.0.
function ipToNumber(ip: string): number {
  return ip.split('.').reduce((acc, octet) => acc * 256 + Number(octet), 0)
}

/** Order two cells' text: IPv4 addresses numerically, anything else case-insensitively. */
export function compareCells(a: string, b: string): number {
  if (IPV4.test(a) && IPV4.test(b)) return ipToNumber(a) - ipToNumber(b)
  const [x, y] = [a.toLowerCase(), b.toLowerCase()]
  return x < y ? -1 : x > y ? 1 : 0
}

/** Sort a table's rows below the heading row by column n: ascending, or descending if they already were. */
export function sortTable(table: HTMLTableElement, n: number): void {
  const rows = [...table.rows].slice(1)
  const text = (row: HTMLTableRowElement): string => row.cells[n]?.textContent ?? ''
  const sorted = [...rows].sort((a, b) => compareCells(text(a), text(b)))
  if (sorted.every((row, i) => row === rows[i])) sorted.reverse()
  rows[0]?.parentNode?.append(...sorted)
}

/** sortTable() by the column with this heading, if there is one. */
export function sortByHeading(table: HTMLTableElement, heading: string): void {
  const n = [...(table.rows[0]?.cells ?? [])].findIndex((cell) => cell.textContent?.trim() === heading)
  if (n !== -1) sortTable(table, n)
}
