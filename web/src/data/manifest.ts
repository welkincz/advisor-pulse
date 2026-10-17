import type { ExportFile, Manifest } from './generated/manifest'

export type Fetch = (url: string) => Promise<Response>

export class DataError extends Error {
  constructor(message: string, readonly url: string) {
    super(message)
    this.name = 'DataError'
  }
}

export async function fetchBytes(fetcher: Fetch, url: string): Promise<Uint8Array> {
  let response: Response
  try {
    response = await fetcher(url)
  } catch {
    throw new DataError(`Could not reach ${url}.`, url)
  }
  if (!response.ok) throw new DataError(`${url} returned HTTP ${response.status}.`, url)
  return new Uint8Array(await response.arrayBuffer())
}

export async function fetchJson<T>(fetcher: Fetch, url: string): Promise<T> {
  const bytes = await fetchBytes(fetcher, url)
  try {
    return JSON.parse(new TextDecoder().decode(bytes)) as T
  } catch {
    throw new DataError(`${url} is not valid JSON.`, url)
  }
}

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes as BufferSource)
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Fetch a file the manifest lists, and refuse it if its sha256 differs from the manifest's. */
export async function fetchVerified(fetcher: Fetch, base: string, file: ExportFile): Promise<Uint8Array> {
  const url = `${base}/${file.name}`
  const bytes = await fetchBytes(fetcher, url)
  if ((await sha256Hex(bytes)) !== file.sha256) {
    throw new DataError(`${file.name} does not match the manifest checksum; the weekly export may be mid-publish.`, url)
  }
  return bytes
}

export function manifestFile(manifest: Manifest, name: string): ExportFile {
  const file = manifest.files.find((f) => f.name === name)
  if (!file) throw new DataError(`The manifest does not list ${name}.`, name)
  return file
}
