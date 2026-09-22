declare module 'file:///patchproof/web_streams.mjs' {
  export function readableFromBytes(
    input: Uint8Array,
    chunkSize?: number,
  ): ReadableStream<Uint8Array>;

  export function collectBytes(
    stream: ReadableStream<Uint8Array>,
  ): Promise<Uint8Array>;
}
