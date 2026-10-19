// The whole frontend: route on the URL path, fetch the one API object that page needs, render it.
//
// The same build runs on both hosts. Locally the web app serves it next to the API, so the API is /api on the same
// origin; the Cloudflare build sets VITE_API_BASE (frontend/.env.cloudflare) to the bucket's domain.
// Links into the app are caught and rendered in place (pushState), so the in-memory API cache below survives
// clicking through. A reload or deep link still works: both hosts answer any non-file path with index.html.

// Bundled by Vite, woff2 files and all. latin only, and only the weights zy.css uses: Noto's 600 is what <b> gets
// instead of a synthesised bold over the 500 body text.
import '@fontsource/fira-code/latin-400.css'
import '@fontsource/fira-code/latin-500.css'
import '@fontsource/fira-code/latin-600.css'
import '@fontsource/fira-code/latin-700.css'
import '@fontsource/noto-sans-display/latin-400.css'
import '@fontsource/noto-sans-display/latin-400-italic.css'
import '@fontsource/noto-sans-display/latin-500.css'
import '@fontsource/noto-sans-display/latin-500-italic.css'
import '@fontsource/noto-sans-display/latin-600.css'
import { html, type SafeHtml } from './html.ts'
import { sortByHeading, sortTable } from './sort.ts'

const API: string = import.meta.env.VITE_API_BASE ?? '/api'

type Vars = Record<string, unknown>

interface Index {
  version: string
  repo_url: string
  built_at: string
  inventories: Record<string, { url: string; base_url: string }>
}

interface Inventory {
  schema_mapping: Record<string, string>
  groups: string[]
  hosts: Record<string, { groups: string[]; vars: Vars }>
}

interface VarsPage {
  vars: Vars
  vars_yaml: string
}

type Page = { title: string; body: SafeHtml }

const seg = encodeURIComponent

// ponytail: kept for the life of the tab, so a tab left open past a rebuild shows the old data until reloaded.
const cache = new Map<string, Promise<unknown>>()

function get<T>(key: string, priority: RequestPriority = 'auto'): Promise<T> {
  let body = cache.get(key)
  if (!body) {
    body = fetch(`${API}/${key}`, { priority }).then((response) => {
      if (!response.ok) throw new Error(`${key}: HTTP ${response.status}`)
      return response.json()
    })
    // A failed fetch is forgotten so the next visit retries it. This also handles the rejection for prefetches,
    // which nothing awaits.
    body.catch(() => cache.delete(key))
    cache.set(key, body)
  }
  return body as Promise<T>
}

const homeLink = html`<a href="/">Inventories</a>`

/** A var as a table cell: '-' when the host doesn't set it, JSON for anything that isn't a scalar. */
function cell(value: unknown): unknown {
  if (value === undefined || value === null) return '-'
  return typeof value === 'object' ? JSON.stringify(value) : value
}

function join(items: SafeHtml[], separator: string): SafeHtml[] {
  return items.flatMap((item, i) => (i ? [html`${separator}`, item] : [item]))
}

async function home(): Promise<Page> {
  const index = await get<Index>('inventories.json')
  const rows = Object.entries(index.inventories).map(
    ([name, inventory]) =>
      html`<tr><td><a href="/inventory/${seg(name)}">${name}</a></td><td><a href="${inventory.url}">source</a></td><td>${inventory.base_url}</td></tr>`,
  )
  const generated = index.built_at ? html`<br />Generated: ${index.built_at}` : ''

  return {
    title: 'Ansible Inventory CMDB',
    body: html`<p><b>Inventories</b></p>
        <table>
            <tr>
                <th>Inventory</th>
                <th>Source URL</th>
                <th>Derived base URL</th>
            </tr>
        ${rows}
        </table>
        <footer><small><a href="${index.repo_url}">${index.version}</a>${generated}</small></footer>`,
  }
}

async function inventory(name: string): Promise<Page> {
  const inv = await get<Inventory>(`inventory/${seg(name)}.json`)
  const base = `/inventory/${seg(name)}`
  const columns = Object.entries(inv.schema_mapping)

  // Every vars page this one links to, fetched at low priority so clicking through renders from memory.
  for (const host of Object.keys(inv.hosts)) get(`inventory/${seg(name)}/host/${seg(host)}.json`, 'low')
  const linkedGroups = new Set(Object.values(inv.hosts).flatMap((host) => host.groups)) // includes 'all'
  for (const group of linkedGroups) get(`inventory/${seg(name)}/group/${seg(group)}.json`, 'low')

  const header = columns.map(([, heading]) => html`<th>${heading}</th>`)
  const rows = Object.entries(inv.hosts).map(
    ([host, data]) => html`
            <tr>
                ${columns.map(([key]) => html`<td>${cell(data.vars[key])}</td>`)}
                <td><a href="${base}/host/${seg(host)}">${host}</a></td>
                <td>${join(
                  data.groups.map((group) => html`<a href="${base}/group/${seg(group)}">${group}</a>`),
                  ', ',
                )}</td>
            </tr>`,
  )
  const groupJson = join(
    inv.groups.map((group) => html`<a href="${API}${base}/group/${seg(group)}/hosts.json">${group}</a>`),
    ' | ',
  )

  return {
    title: `Inventory: ${name}`,
    body: html`<p>${homeLink} / <b>${name}</b></p>
        <table id="Hosts">
            <tr>
                ${header}<th>Host Vars</th><th>Group Vars</th>
            </tr>${rows}
        </table>
        ${inv.groups.length ? html`<h4>Group JSON</h4><code style="width: fit-content;">${groupJson}</code>` : ''}`,
  }
}

async function vars(name: string, kind: 'host' | 'group', thing: string): Promise<Page> {
  const page = await get<VarsPage>(`inventory/${seg(name)}/${kind}/${seg(thing)}.json`)
  const label = kind === 'host' ? 'Host vars' : 'Group vars'

  return {
    title: `${label}: ${thing}`,
    body: html`<p>${homeLink} / <a href="/inventory/${seg(name)}">${name}</a> / ${label}: <b>${thing}</b></p>
        <code>${page.vars_yaml}</code>`,
  }
}

async function route(path: string): Promise<Page> {
  // The old static site linked every page as <path>/index.html, so bookmarks of those still land here.
  const parts = path
    .replace(/\/index\.html$/, '')
    .split('/')
    .filter(Boolean)
    .map(decodeURIComponent)

  if (parts.length === 0) return home()
  if (parts[0] === 'inventory' && parts.length === 2) return inventory(parts[1])
  if (parts[0] === 'inventory' && parts.length === 4 && (parts[2] === 'host' || parts[2] === 'group')) {
    return vars(parts[1], parts[2], parts[3])
  }
  return { title: 'Not found', body: html`<p>${homeLink}</p><p>No such page.</p>` }
}

async function render(): Promise<void> {
  const app = document.getElementById('app') as HTMLElement
  const path = location.pathname
  try {
    const page = await route(path)
    if (path !== location.pathname) return // navigated again while this one was loading
    document.title = page.title
    app.innerHTML = page.body.toString()
    const hosts = document.getElementById('Hosts')
    if (hosts instanceof HTMLTableElement) sortByHeading(hosts, 'IP Address')
  } catch (error) {
    // Before the first build the API has nothing: a 503 from the web app, a 404 from the bucket.
    app.innerHTML = html`<p>${homeLink}</p>
        <p>Couldn't load ${String(error).replace(/^Error: /, '')}. If the CMDB hasn't been built yet, try again in a
        moment.</p>`.toString()
  }
}

document.addEventListener('click', (event) => {
  const link = (event.target as Element).closest('a')
  if (!link || link.target || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return
  }
  const url = new URL(link.href)
  // Off-site links and the raw API JSON (same origin under the web app's /api) are left to the browser.
  if (url.origin !== location.origin || url.pathname.startsWith(`${API}/`)) return
  event.preventDefault()
  history.pushState(null, '', url)
  render().then(() => scrollTo(0, 0))
})
addEventListener('popstate', render)

document.addEventListener('click', (event) => {
  const heading = (event.target as Element).closest('#Hosts th')
  if (heading instanceof HTMLTableCellElement)
    sortTable(heading.closest('table') as HTMLTableElement, heading.cellIndex)
})

render()
