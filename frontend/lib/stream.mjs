/** Parse SSE across arbitrary network chunk boundaries, including UTF-8 splits. */
export async function readEvents(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  function consume() {
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let name = "message";
      const data = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (!data.length) continue;
      const value = JSON.parse(data.join("\n"));
      if (name === "done") completed = true;
      if (name === "error") throw new Error(value.message || "Unable to answer. Please try again.");
      onEvent(name, value);
    }
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      consume();
    }
    buffer += decoder.decode();
    consume();
    if (!completed) throw new Error("The connection ended before the answer was complete. Please retry.");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
