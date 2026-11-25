import { Client } from "@langchain/langgraph-sdk";

const ASSISTANT_ID = "research_agent"; // langgraph.json의 graphs 키

const client = new Client({ apiUrl: `${window.location.origin}/api` });

export async function createThread() {
  const thread = await client.threads.create();
  return thread.thread_id;
}

/**
 * 같은 thread에서 실행한다. (서버의 체크포인터가 대화 상태를 저장)
 * - args.input  : 새 질문 실행
 * - args.resume : interrupt로 멈춘 실행을 재개 (Command(resume=...))
 * handlers.onUpdate(node, values) : 노드가 끝날 때마다
 * handlers.onToken(text)          : 보고서 토큰이 생성될 때마다
 * handlers.onInterrupt(payload)   : 사용자 확인이 필요해 멈췄을 때
 */
export async function streamRun(threadId, args, handlers, signal) {
  const payload = { streamMode: ["updates", "messages-tuple"], signal };
  if (args.resume !== undefined) payload.command = { resume: args.resume };
  else payload.input = args.input;

  const stream = client.runs.stream(threadId, ASSISTANT_ID, payload);
  for await (const chunk of stream) {
    if (chunk.event === "updates" && chunk.data) {
      for (const [node, values] of Object.entries(chunk.data)) {
        if (node === "__interrupt__") handlers.onInterrupt?.(values?.[0]?.value);
        else handlers.onUpdate?.(node, values ?? {});
      }
    } else if (chunk.event?.startsWith("messages") && Array.isArray(chunk.data)) {
      const [msg, meta] = chunk.data;
      const text = typeof msg?.content === "string" ? msg.content : "";
      if (meta?.langgraph_node === "write_report" && text) handlers.onToken?.(text);
    } else if (chunk.event === "error") {
      throw new Error(chunk.data?.message || chunk.data?.error || "서버 오류가 발생했습니다.");
    }
  }
}
