// Deterministic Web Streams plumbing for verifier-generated Node/TypeScript tests.
// Application behavior still comes from repository modules; this helper only
// creates byte streams and collects their output without reimplementing app logic.

export function readableFromBytes(bytes, segmentSize = bytes.byteLength || 1) {
  if (!(bytes instanceof Uint8Array)) {
    throw new TypeError('readableFromBytes expects a Uint8Array');
  }
  if (!Number.isSafeInteger(segmentSize) || segmentSize <= 0) {
    throw new RangeError('segmentSize must be a positive safe integer');
  }

  return new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < bytes.byteLength; offset += segmentSize) {
        controller.enqueue(bytes.slice(offset, offset + segmentSize));
      }
      controller.close();
    },
  });
}

export async function collectBytes(readable) {
  const chunks = [];
  let length = 0;
  for await (const chunk of readable) {
    if (!(chunk instanceof Uint8Array)) {
      throw new TypeError('collectBytes expects Uint8Array chunks');
    }
    const copy = chunk.slice();
    chunks.push(copy);
    length += copy.byteLength;
  }

  const result = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}
