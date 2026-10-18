// Inventory values come from someone's git repo and end up in innerHTML, so nothing gets interpolated raw.
// Jinja's autoescape used to do this job.

/** Markup that is already escaped, so html`` fragments nest without being escaped twice. */
export class SafeHtml {
  readonly value: string

  constructor(value: string) {
    this.value = value
  }

  toString(): string {
    return this.value
  }
}

const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

function render(value: unknown): string {
  if (value instanceof SafeHtml) return value.value
  if (Array.isArray(value)) return value.map(render).join('')
  return String(value).replace(/[&<>"']/g, (char) => ESCAPES[char])
}

/** Tagged template that escapes every interpolation, except html`` fragments and arrays of them. */
export function html(strings: TemplateStringsArray, ...values: unknown[]): SafeHtml {
  return new SafeHtml(strings.reduce((out, string, i) => out + render(values[i - 1]) + string))
}
