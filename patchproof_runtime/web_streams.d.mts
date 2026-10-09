/** Portable declarations for the bundled byte-stream helpers. */
export function readableFromBytes(bytes: Uint8Array, segmentSize?: number): ReadableStream<Uint8Array>;
export function collectBytes(readable: ReadableStream<Uint8Array>): Promise<Uint8Array>;
