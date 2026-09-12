/**
 * Client-side upload guardrails.
 *
 * This is a UX filter and a first speed bump, NOT the security boundary — a browser
 * can always be bypassed (a raw API call skips this entirely). The Content-Type/extension
 * a browser reports is attacker-controlled, so the only client-side check worth doing is
 * sniffing real magic bytes and refusing to even decode oversized images. The actual
 * trust boundary belongs server-side once the detection services exist — see
 * SECURITY.md at the repo root for what each service must additionally do
 * (independent re-validation, re-encoding, AV scan, sandboxing).
 */

export const MAX_IMAGE_BYTES = 15 * 1024 * 1024
export const MAX_VIDEO_BYTES = 50 * 1024 * 1024
export const MAX_IMAGE_PIXELS = 30_000_000 // ~30MP; guards against decompression-bomb-style images

export interface GuardResult {
  ok: boolean
  reason?: string
}

type Sniffed = 'image/png' | 'image/jpeg' | 'image/webp' | 'video/mp4' | null

async function sniff(file: File): Promise<Sniffed> {
  const bytes = new Uint8Array(await file.slice(0, 16).arrayBuffer())
  const matches = (offset: number, sig: number[]) => sig.every((b, i) => bytes[offset + i] === b)

  if (matches(0, [0x89, 0x50, 0x4e, 0x47])) return 'image/png'
  if (matches(0, [0xff, 0xd8, 0xff])) return 'image/jpeg'
  if (matches(0, [0x52, 0x49, 0x46, 0x46]) && matches(8, [0x57, 0x45, 0x42, 0x50])) return 'image/webp'
  if (matches(4, [0x66, 0x74, 0x79, 0x70])) return 'video/mp4' // 'ftyp' box — covers mp4 and mov
  return null
}

/** Rejects files whose real bytes don't match a known image/video signature, are too
 * large, or (for images) decode to a pixel count large enough to be a memory-exhaustion
 * attempt. Renamed executables, HTML/SVG polyglots and mislabeled files are all caught
 * by the signature check since none of them start with a real image/video magic number. */
export async function guardFile(file: File, allowVideo: boolean): Promise<GuardResult> {
  if (file.size === 0) return { ok: false, reason: 'File is empty' }

  const sniffed = await sniff(file)
  if (!sniffed) {
    return { ok: false, reason: "File content doesn't match a supported image/video format" }
  }

  const isVideo = sniffed === 'video/mp4'
  if (isVideo && !allowVideo) {
    return { ok: false, reason: 'Video not accepted here — upload an image' }
  }

  const maxBytes = isVideo ? MAX_VIDEO_BYTES : MAX_IMAGE_BYTES
  if (file.size > maxBytes) {
    return { ok: false, reason: `File exceeds the ${Math.round(maxBytes / (1024 * 1024))}MB limit` }
  }

  if (!isVideo) {
    try {
      const bitmap = await createImageBitmap(file)
      const pixels = bitmap.width * bitmap.height
      bitmap.close()
      if (pixels > MAX_IMAGE_PIXELS) {
        return { ok: false, reason: 'Image resolution is too large' }
      }
    } catch {
      return { ok: false, reason: 'Image could not be decoded — file may be corrupt' }
    }
  }

  return { ok: true }
}
