import { expect, test } from 'vitest'

import { html } from './html.ts'

test('interpolations are escaped', () => {
  const host = `<img src=x onerror="alert('x')">&`
  expect(html`<td title="${host}">${host}</td>`.toString()).toBe(
    '<td title="&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;">' +
      '&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;</td>',
  )
})

test('nested fragments and arrays are not escaped twice', () => {
  const rows = ['a&b', 'c'].map((name) => html`<li>${name}</li>`)
  expect(html`<ul>${rows}</ul>`.toString()).toBe('<ul><li>a&amp;b</li><li>c</li></ul>')
})

test('non-strings are stringified', () => {
  expect(html`${0}|${false}|${null}`.toString()).toBe('0|false|null')
})
