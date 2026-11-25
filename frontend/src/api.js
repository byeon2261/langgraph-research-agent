import { Client } from "@langchain/langgraph-sdk";

const ASSISTANT_ID = "research_agent"; // langgraph.json의 graphs 키

const client = new Client({ apiUrl: `${window.location.origin}/api` });

/**
 * 질문을 실행하고 노드가 끝날 때마다 onUpdate(nodeName, values)를 호출한다.
 */
export async function runResearch(question, onUpdate, signal) {
  const thread = await client.threads.create();
  const stream = client.runs.stream(thread.thread_id, ASSISTANT_ID, {
    input: { question, loop_count: 0 },
    streamMode: "updates",
    signal,
  });
  for await (const chunk of stream) {
    if (chunk.event === "updates" && chunk.data) {
      for (const [node, values] of Object.entries(chunk.data)) {
        onUpdate(node, values ?? {});
      }
    } else if (chunk.event === "error") {
      throw new Error(chunk.data?.message || "서버 오류가 발생했습니다.");
    }
  }
}
