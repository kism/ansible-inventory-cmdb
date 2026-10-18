import assert from 'node:assert/strict'
import { test } from 'node:test'

import { html } from './html.ts'

test('interpolations are escaped', () => {
  const host = `<img src=x onerror="alert('x')">&`
  assert.equal(
    html`<td title="${host}">${host}</td>`.toString(),
    '<td title="&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;">' +
      '&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;</td>',
  )
})

test('nested fragments and arrays are not escaped twice', () => {
  const rows = ['a&b', 'c'].map((name) => html`<li>${name}</li>`)
  assert.equal(html`<ul>${rows}</ul>`.toString(), '<ul><li>a&amp;b</li><li>c</li></ul>')
})

test('non-strings are stringified', () => {
  assert.equal(html`${0}|${false}|${null}`.toString(), '0|false|null')
})
